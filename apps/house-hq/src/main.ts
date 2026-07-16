import * as THREE from "three";
import "./styles.css";
import {
  createVrmEmbodiment,
  resolveVrmBodyYawFromDisplacement,
  type VrmEmbodiment,
  type VrmEmbodimentDebug,
} from "./vrmEmbodiment";
import {
  VoiceQueueFullError,
  createHouseVoiceSessionCoordinator,
  createVoiceAvatarPlaybackSignal,
  type VoiceSessionState,
} from "./voiceSession";
import {
  createDesktopHttpDataSource,
  createDesktopPanel,
  createSourceWorkspaceHttpDataSource,
  type DesktopActionIntent,
  type DesktopActionReceipt,
  type DesktopPanelController,
  type DesktopPanelItem,
  type DesktopPanelMode,
} from "./desktopPanel";
import { attachInternalsSnapshot, mountInternalsMap, renderInternalsMap, type InternalsSnapshot } from "./internalsMap";
import { recoverAlpeccaEndpoint } from "./endpointRecovery";

window.addEventListener("vite:preloadError", (event) => {
  event.preventDefault();
  void recoverAlpeccaEndpoint("stale-module-chunk", { force: true });
});

type AlpeccaRuntimeProbe = {
  ready: boolean;
  state: string;
  folder: string;
  artBaseUrl: string;
  artAssetMode: string;
  artManifestUrl: string;
  matrixAction: string;
  matrixAssetKey: string;
  matrixRequestedKey: string;
  matrixLoadedKey: string;
  matrixFallbackState: string;
  matrixFolder: string;
  matrixFrameCount: number;
  matrixSourceFamily: string;
  matrixApprovalStatus: AlpeccaSourceStatus;
  matrixManifestStatus: AlpeccaMatrixManifestStatus;
  matrixResolution: AlpeccaMatrixResolution;
  matrixLayerPlan: string;
  matrixFootAnchor: string;
  matrixContactFrames: string;
  matrixDepthProxy: string;
  intent: AlpeccaIntent;
  animationSourceFamily: string;
  animationSourceStatus: AlpeccaSourceStatus;
  animationSourceFlagged: boolean;
  flipX: boolean;
  perceptionTarget: string;
  frameIndex: number;
  frameCount: number;
  moving: boolean;
  direction: string;
  worldDirection: string;
  screenDirection: string;
  directionCandidate: string;
  directionCandidateFrames: number;
  billboardYaw: number;
  groundYaw: number;
  footContact: string;
  presence: number;
  bodyLean: number;
  mirrorReflection: number;
  groundContact: number;
  floorReflection: number;
  animationLock: number;
  dwell: number;
  walkPause: number;
  movementLoaded: number;
  movementTotal: number;
  movementMissing: string[];
  animationLoaded: number;
  animationTotal: number;
  animationMissing: string[];
  walkIntent: boolean;
  movedDistance: number;
  walkPlaybackRate: number;
  walkSpeed: number;
  talking: boolean;
  mouthOpen: number;
  profileMouthMode: string;
  profileTalkFrame: string;
  voiceEngine: string;
  voiceName: string;
  voiceProfile: string;
  voicePreview: string;
  voicePrimary: string;
  voiceTempo: string;
  voiceRate: string;
  voiceSpeed: string;
  voiceStyle: string;
  voiceWarmth: string;
  voiceBreath: string;
  voiceEmotionTimer: number;
  voiceEmotionState: Record<string, number>;
  freedomAction: string;
  worldTickTimer: number;
  worldTickInFlight: boolean;
  walkFrameRate: number;
  frameTime: number;
  loopCount: number;
  droppedFrames: number;
  heightClass: string;
  standingScaleLocked: boolean;
  silhouetteWidth: number;
  legWidthRatio: number;
  profileMode: string;
  profileExpression: string;
  activeFeature: string;
  lastSeen: string;
  lastQuestion: string;
  ideaObjects: number;
  debugLocked: boolean;
  debugLockState: string;
  scaleY: number;
  spriteY: number;
  strideX: number;
  x: number;
  z: number;
  routeStep: string;
  viewVertical: string;
  viewHorizontal: string;
  viewMatrix: string;
  relativeYawDeg: number;
  cameraPitchDeg: number;
  viewVolumeZone: string;
  viewVolumeProbe: string;
  viewVolumeDepth: number;
  viewSampleY: number;
  viewSector16: number;
  viewSector16Key: string;
  cylinderRadius: number;
  cylinderZone: string;
  cylinderPlayerAngleDeg: number;
  cylinderPlayerDistance: number;
  cylinderVerticalTier: string;
  cylinderMovementClamped: boolean;
  cylinderQaVisible: boolean;
  billboardMode: string;
  billboardClampDeg: number;
  stageRoom: string;
  stagePad: string;
  stageQaIssues: string[];
  navClearance: string;
  renderCalls: number;
  pixelRatio: number;
};

declare global {
  interface Window {
    __HOUSE_DEBUG__?: {
      camera: THREE.PerspectiveCamera;
      player: typeof player;
      alpecca?: {
        ready: boolean;
        state: string;
        folder?: string;
        artBaseUrl?: string;
        artAssetMode?: string;
        artManifestUrl?: string;
        matrixAction?: string;
        matrixAssetKey?: string;
        matrixRequestedKey?: string;
        matrixLoadedKey?: string;
        matrixFallbackState?: string;
        matrixFolder?: string;
        matrixFrameCount?: number;
        matrixSourceFamily?: string;
        matrixApprovalStatus?: AlpeccaSourceStatus;
        matrixManifestStatus?: AlpeccaMatrixManifestStatus;
        matrixResolution?: AlpeccaMatrixResolution;
        matrixLayerPlan?: string;
        matrixFootAnchor?: string;
        matrixContactFrames?: string;
        matrixDepthProxy?: string;
        intent?: AlpeccaIntent;
        animationSourceFamily?: string;
        animationSourceStatus?: AlpeccaSourceStatus;
        animationSourceFlagged?: boolean;
        flipX?: boolean;
        perceptionTarget?: string;
        frameIndex?: number;
        frameCount?: number;
        moving?: boolean;
        direction?: string;
        worldDirection?: string;
        screenDirection?: string;
        directionCandidate?: string;
        directionCandidateFrames?: number;
        inspecting?: string;
        destination?: string;
        markers?: number;
        interacting?: string;
        stuck?: number;
        routeStep?: string;
        scaleX?: number;
        scaleY?: number;
        movementLoaded?: number;
        movementTotal?: number;
        movementMissing?: string[];
        animationLoaded?: number;
        animationTotal?: number;
        animationMissing?: string[];
        talking?: boolean;
        mouthOpen?: number;
        profileMouthMode?: string;
        profileTalkFrame?: string;
        voiceEngine?: string;
        voiceName?: string;
        voiceProfile?: string;
        voicePreview?: string;
        voicePrimary?: string;
        voiceTempo?: string;
        voiceRate?: string;
        voiceSpeed?: string;
        voiceStyle?: string;
        voiceWarmth?: string;
        voiceBreath?: string;
        voiceEmotionTimer?: number;
        voiceEmotionState?: Record<string, number>;
        freedomAction?: string;
        worldTickTimer?: number;
        worldTickInFlight?: boolean;
        frameTime?: number;
        loopCount?: number;
        droppedFrames?: number;
        heightClass?: string;
        standingScaleLocked?: boolean;
        silhouetteWidth?: number;
        legWidthRatio?: number;
        walkPlaybackRate?: number;
        walkSpeed?: number;
        profileMode?: string;
        profileExpression?: string;
        activeFeature?: string;
        lastSeen?: string;
        lastQuestion?: string;
        animationLock?: number;
        dwell?: number;
        walkPause?: number;
        groundContact?: number;
        floorReflection?: number;
        debugLocked?: boolean;
        debugLockState?: string;
        viewVertical?: string;
        viewHorizontal?: string;
        viewMatrix?: string;
        relativeYawDeg?: number;
        cameraPitchDeg?: number;
        viewVolumeZone?: string;
        viewVolumeProbe?: string;
        viewVolumeDepth?: number;
        viewSampleY?: number;
        viewSector16?: number;
        viewSector16Key?: string;
        cylinderRadius?: number;
        cylinderZone?: string;
        cylinderPlayerAngleDeg?: number;
        cylinderPlayerDistance?: number;
        cylinderVerticalTier?: string;
        cylinderMovementClamped?: boolean;
        cylinderQaVisible?: boolean;
        billboardMode?: string;
        billboardClampDeg?: number;
        stageRoom?: string;
        stagePad?: string;
        stageQaIssues?: string[];
        navClearance?: string;
        vrm?: VrmEmbodimentDebug;
        x: number;
        z: number;
      };
      sourceDashboard?: {
        ready: boolean;
        activeFeatureId: string;
        nodes: number;
        status: string;
      };
      stage?: {
        rooms: number;
        issues: string[];
      };
    };
    __ALPECCA_RUNTIME__?: AlpeccaRuntimeProbe;
    __HOUSE_STEP__?: (dt?: number, frames?: number) => AlpeccaRuntimeProbe | undefined;
    __ALPECCA_ANIMATION_STATES__?: AlpeccaAnimationName[];
    __ALPECCA_PLAY_ANIMATION__?: (name: AlpeccaAnimationName, seconds?: number) => AlpeccaRuntimeProbe | undefined;
    __ALPECCA_LOCK_ANIMATION__?: (name: AlpeccaAnimationName, seconds?: number) => AlpeccaRuntimeProbe | undefined;
  }
}

type Wall = { minX: number; maxX: number; minZ: number; maxZ: number };
type SpriteFrame = { x: number; y: number; w: number; h: number; duration?: number };
type SpriteAtlas = {
  frames: Record<string, SpriteFrame>;
  meta?: { frame_size?: { w?: number; h?: number } };
};
type AlpeccaChatExpressionFrame = {
  index: number;
  x: number;
  y: number;
  w: number;
  h: number;
  label: string;
  talking?: boolean;
  listening?: boolean;
  blink?: boolean;
};
type AlpeccaChatExpressionAtlas = {
  image: string;
  fallbackImage: string;
  frameSize: number;
  columns: number;
  frames: AlpeccaChatExpressionFrame[];
  talkCycle: number[];
  listenCycle: number[];
  blinkCycle: number[];
};
type AlpeccaAnimationName =
  | "idle"
  | "walk"
  | "wave"
  | "sit"
  | "point"
  | "dance"
  | "victory"
  | "sleep"
  | "pickup"
  | "run"
  | "climb"
  | "crouch"
  | "dash"
  | "jump"
  | "jumpDown"
  | "jumpSide"
  | "jumpSoutheast"
  | "jumpUp"
  | "kneel"
  | "sleepDown"
  | "sleepNortheast"
  | "sleepSoutheast"
  | "sleepUp"
  | "waveDown"
  | "waveNortheast"
  | "waveUp"
  | "idleDown"
  | "idleUp"
  | "idleSide"
  | "idleNortheast"
  | "idleSoutheast"
  | "talkDown"
  | "walkDown"
  | "walkUp"
  | "walkSide"
  | "walkLeft"
  | "walkNortheast"
  | "walkNorthwest"
  | "walkSoutheast"
  | "walkSouthwest"
  | "runDown"
  | "runUp"
  | "runSide"
  | "runNortheast"
  | "runSoutheast";
type AlpeccaIntent = "observing" | "approaching" | "greeting" | "listening" | "thinking" | "replying" | "inspecting" | "remembering" | "creating" | "idle";
type AlpeccaSourceStatus = "approved" | "runtime-ok" | "qa-only" | "needs-regeneration";
type AlpeccaAnimation = {
  texture: THREE.Texture;
  frames: SpriteFrame[];
  frameIndex: number;
  elapsed: number;
  secondsPerFrame: number;
  folder: string;
  textureSource: string;
  sourceFamily: string;
  sourceStatus: AlpeccaSourceStatus;
  sourceFlagged: boolean;
  visualScale: number;
  spriteY: number;
  heightClass: string;
  silhouetteWidth: number;
  legWidthRatio: number;
  loop: boolean;
  completed: boolean;
};
type AlpeccaVisualMeta = {
  visualScale?: number;
  spriteY?: number;
  frameSize?: number;
  alphaBounds?: { x?: number; y?: number; w?: number; h?: number };
  mirroredFrom?: string;
  proportion?: {
    maxFrameWidth?: number;
    lowerBodyWidthRatio?: number;
    lowerBodyWidthVariance?: number;
    flagged?: boolean;
  };
};
type AlpeccaAnimationConfig = { folder: string; secondsPerFrame: number; loop?: boolean };
type AlpeccaAiStatus = "offline" | "connecting" | "live" | "token";
type AlpeccaModelUse = {
  requested_tier?: string;
  used_tier?: string;
  backend?: string;
  model?: string;
  ok?: boolean;
  fallback?: boolean;
  error?: string;
  deep_backend?: string;
};
type AlpeccaMemoryEvidence = {
  id?: number;
  kind?: string;
  content?: string;
  salience?: number;
  score?: number;
  similarity?: number;
  recency?: number;
  method?: string;
};
type AlpeccaMindpageState = {
  enabled?: boolean;
  source?: string;
  context_fill?: number;
  pressure_score?: number;
  pressure?: string;
  page_count?: number;
  hot_page_count?: number;
  history_messages?: number;
  turns_until_history_eviction?: number;
  unsummarized_eviction_backlog?: number;
};
type AlpeccaSourceRef = {
  root: string;
  rel: string;
};
type AlpeccaCapabilityPurpose =
  | "camera_frame"
  | "push_to_talk"
  | "screen_share"
  | "voice_enrollment"
  | "file_source_ref";
type AlpeccaCapabilityConnection = {
  id: string;
  surface: "house-hq";
  principal: "creator";
};
type AlpeccaCapabilityLease = {
  leaseId: string;
  token: string;
  purpose: AlpeccaCapabilityPurpose;
  connectionId: string;
  expiresAt: number;
  expiryTimer: number | null;
  stopped: boolean;
};
type AlpeccaAiMessage = {
  type?: string;
  request_id?: string;
  source?: string;
  reply?: string;
  spoken_reply?: string;
  spoken_text?: string;
  speech_cues?: Record<string, unknown>;
  text?: string;
  message?: string;
  content?: string;
  mood?: string;
  state?: Record<string, number>;
  capability_connection?: {
    id?: string;
    surface?: string;
    principal?: string;
  };
  llm_online?: boolean;
  model_use?: AlpeccaModelUse;
  memory_evidence?: AlpeccaMemoryEvidence[];
  mindpage?: AlpeccaMindpageState;
  cognition?: {
    models?: { last_call?: AlpeccaModelUse };
    intent?: Record<string, unknown>;
    mindpage?: AlpeccaMindpageState;
  };
  living_loop?: {
    ok?: boolean;
    phase?: string;
    line?: string;
    question?: string;
    activated_system?: {
      id?: string;
      label?: string;
      status?: string;
      summary?: string;
      warmup?: { ok?: boolean; engine?: string; error?: string };
    };
    room?: { id?: string; name?: string; purpose?: string };
    creator?: { name?: string; speaker?: string; fresh_evidence?: boolean };
    intent?: { name?: string; reason?: string; target?: string };
    self_feedback?: { noticed?: string; learned?: string; next_action?: string; needs_creator_input?: boolean };
    next_action?: { system?: string; target?: string; room?: string; action?: string; approval?: string };
    learning_record?: Record<string, unknown>;
    engagement_proposal?: { id?: number; action?: string; status?: string };
    proposal?: { id?: number; action?: string; status?: string };
    memory_id?: number;
    journal_id?: number;
  };
  summary?: string;
  error?: string;
  detail?: string;
  code?: string;
  reason?: string;
};
type AlpeccaAutonomyState = {
  enabled?: boolean;
  last_living_at?: number;
  last_living_reason?: string;
  last_living_line?: string;
  last_living_system?: string;
  last_living_room?: string;
  last_living_question?: string;
  last_living_observation_id?: string | number | null;
  last_living_memory_id?: string | number | null;
  last_living_journal_id?: string | number | null;
  last_learning_record_id?: string | number | null;
  last_living_self_feedback?: { noticed?: string; learned?: string; next_action?: string; needs_creator_input?: boolean };
  last_living_next_action?: { system?: string; target?: string; room?: string; action?: string; approval?: string };
  last_living_engagement_proposal?: { id?: number; action?: string; status?: string };
  current_intent?: { name?: string; reason?: string; target?: string };
};
type AlpeccaSourceFeature = {
  id: string;
  label: string;
  room: string;
  prompt: string;
  page?: string;
  toolPath?: string;
  color: string;
};
type OfficeRoom = {
  id: string;
  name: string;
  stationId: string;
  purpose: string;
  system: string;
  bounds: { minX: number; maxX: number; minZ: number; maxZ: number };
};
type AlpeccaViewVerticalTier = "low" | "eye" | "high";
type AlpeccaViewHorizontalTier = "front" | "frontDiag" | "side" | "backDiag" | "back";
type AlpeccaViewSector16Key =
  | "s00"
  | "s01"
  | "s02"
  | "s03"
  | "s04"
  | "s05"
  | "s06"
  | "s07"
  | "s08"
  | "s09"
  | "s10"
  | "s11"
  | "s12"
  | "s13"
  | "s14"
  | "s15";
type AlpeccaViewMatrixState = {
  vertical: AlpeccaViewVerticalTier;
  horizontal: AlpeccaViewHorizontalTier;
  flipX: boolean;
  relativeYawDeg: number;
  cameraPitchDeg: number;
  sector16: number;
  sector16Key: AlpeccaViewSector16Key;
  cylinderRadius: number;
  cylinderZone: string;
  cylinderPlayerDistance: number;
  volumeZone: string;
  volumeProbe: string;
  volumeDepth: number;
  sampleY: number;
  billboardClampDeg: number;
  key: string;
};
type AlpeccaMatrixAction = "idle" | "listen" | "talk" | "walk" | "wave" | "inspect" | "careful" | "rest" | "sleep";
type AlpeccaMatrixManifestStatus = "pending" | "loaded" | "fallback";
type AlpeccaMatrixResolution = "exact" | "vertical-fallback" | "local-fallback";
type AlpeccaRuntimeLayerRole = "base-body" | "expression-overlay" | "mouth-eye-overlay" | "contact-shadow" | "depth-proxy" | "floor-reflection";
type AlpeccaRuntimeLayerPlan = {
  roles?: AlpeccaRuntimeLayerRole[];
  expressionOverlay?: boolean;
  mouthEyeOverlay?: boolean;
  contactShadow?: boolean;
  depthProxy?: boolean;
  floorReflection?: boolean;
  transitionSeconds?: number;
};
type AlpeccaRuntimeMatrixRecord = {
  key: string;
  action: AlpeccaMatrixAction;
  verticalTier: AlpeccaViewVerticalTier;
  horizontalTier: AlpeccaViewHorizontalTier | string;
  state: AlpeccaAnimationName;
  folder: string;
  frameCount: number;
  sourceFamily: string;
  approvalStatus: AlpeccaSourceStatus;
  heightClass?: string;
  visualScale?: number;
  spriteY?: number;
  footAnchor?: string;
  contactFrameIndexes?: number[];
  layerPlan?: AlpeccaRuntimeLayerPlan;
  depthProxy?: string;
  notes?: string;
};
type AlpeccaRuntimeMatrixManifest = {
  schemaVersion?: number;
  generatedAt?: string;
  assetRoot?: string;
  records?: AlpeccaRuntimeMatrixRecord[];
};
type AlpeccaMatrixAssetProbe = {
  action: AlpeccaMatrixAction;
  assetKey: string;
  requestedKey: string;
  loadedKey: string;
  fallbackState: AlpeccaAnimationName;
  folder: string;
  frameCount: number;
  sourceFamily: string;
  approvalStatus: AlpeccaSourceStatus;
  manifestStatus: AlpeccaMatrixManifestStatus;
  resolution: AlpeccaMatrixResolution;
  layerPlan: string;
  footAnchor: string;
  contactFrames: string;
  depthProxy: string;
};
type RoomStageRect = {
  label: string;
  center: THREE.Vector3;
  size: THREE.Vector2;
  color: string;
};
type RoomStageSpec = {
  roomId: string;
  walkable: RoomStageRect;
  safeLane: RoomStageRect;
  stagePad: RoomStageRect;
  inspectPad: RoomStageRect;
  chatPad: RoomStageRect;
  restPad?: RoomStageRect;
  portals: Array<{ id: string; to: string; center: THREE.Vector3; width: number }>;
  terminals: string[];
  occlusionPlanes: RoomStageRect[];
};
type AlpeccaSourcePlate = {
  id: string;
  label: string;
  hint: string;
  file: string;
};
type AlpeccaExplorePoint = {
  roomId: string;
  roomName: string;
  label: string;
  position: THREE.Vector3;
  lookAt: THREE.Vector3;
  animation: AlpeccaAnimationName;
  freedomAnimations?: AlpeccaAnimationName[];
  featureId?: string;
  restOnly?: boolean;
  action: string;
  marker?: THREE.Group;
  markerMaterial?: THREE.MeshBasicMaterial;
  markerLight?: THREE.PointLight;
  markerBeam?: THREE.Mesh<THREE.CylinderGeometry, THREE.MeshBasicMaterial>;
  markerGlyph?: THREE.Mesh<THREE.OctahedronGeometry, THREE.MeshBasicMaterial>;
};
type AlpeccaRoomDevice = {
  roomId: string;
  label: string;
  group: THREE.Group;
  material: THREE.MeshBasicMaterial;
  light: THREE.PointLight;
  pulseTimer: number;
};
type AlpeccaSourceTerminal = {
  featureId: string;
  group: THREE.Group;
  accentMaterial: THREE.MeshStandardMaterial;
  signalMaterial: THREE.MeshBasicMaterial;
  light: THREE.PointLight;
  baseYaw: number;
  pulseTimer: number;
  autonomousTimer: number;
};
type AlpeccaTerminalHand = "left" | "right";
type AlpeccaTerminalPhase = "approach" | "reach" | "contact" | "retract";
type AlpeccaTerminalTiming = {
  reachSeconds: number;
  contactSeconds: number;
  retractSeconds: number;
};
type AlpeccaTerminalTarget = {
  id: string;
  featureId: string;
  roomId: string;
  label: string;
  group: THREE.Group;
  approach: THREE.Vector3;
  attention: THREE.Vector3;
  contact: THREE.Vector3;
  contactNormal: THREE.Vector3;
  hand: AlpeccaTerminalHand;
  timing: AlpeccaTerminalTiming;
};
type AlpeccaSourceDashboardNode = {
  featureId: string;
  material: THREE.MeshBasicMaterial;
  railMaterial: THREE.MeshBasicMaterial;
  mesh: THREE.Mesh<THREE.SphereGeometry, THREE.MeshBasicMaterial>;
  rail: THREE.Mesh<THREE.BoxGeometry, THREE.MeshBasicMaterial>;
  light: THREE.PointLight;
  pulseTimer: number;
};
type AlpeccaSourceDashboard = {
  group: THREE.Group;
  nodes: AlpeccaSourceDashboardNode[];
  core: THREE.Mesh<THREE.OctahedronGeometry, THREE.MeshBasicMaterial>;
  coreMaterial: THREE.MeshBasicMaterial;
  statusMaterial: THREE.MeshBasicMaterial;
  statusLight: THREE.PointLight;
  pulseTimer: number;
  activeFeatureId: string;
};
type AlpeccaSourceGalleryPanel = {
  plateId: string;
  roomId: string;
  group: THREE.Group;
  art: THREE.Mesh<THREE.PlaneGeometry, THREE.MeshBasicMaterial>;
  accentMaterial: THREE.MeshBasicMaterial;
  core: THREE.Mesh<THREE.OctahedronGeometry, THREE.MeshBasicMaterial>;
  light: THREE.PointLight;
  pulseTimer: number;
};
type AlpeccaExpressionProjector = {
  group: THREE.Group;
  portrait: THREE.Mesh<THREE.PlaneGeometry, THREE.MeshBasicMaterial>;
  frameMaterial: THREE.MeshBasicMaterial;
  core: THREE.Mesh<THREE.OctahedronGeometry, THREE.MeshBasicMaterial>;
  light: THREE.PointLight;
  current: string;
  pulseTimer: number;
};
type AlpeccaAvatarAsset = {
  id: string;
  label: string;
  file: string;
};
type AlpeccaAvatarStation = {
  group: THREE.Group;
  image: THREE.Mesh<THREE.PlaneGeometry, THREE.MeshBasicMaterial>;
  frameMaterial: THREE.MeshBasicMaterial;
  core: THREE.Mesh<THREE.OctahedronGeometry, THREE.MeshBasicMaterial>;
  light: THREE.PointLight;
  current: string;
  pulseTimer: number;
};
type AlpeccaDetailPoint = {
  id: string;
  roomId: string;
  label: string;
  note: string;
  group: THREE.Group;
  material: THREE.MeshBasicMaterial;
  light: THREE.PointLight;
  pulseTimer: number;
  cooldown: number;
};
type AlpeccaMemoryTrace = {
  roomId: string;
  roomName: string;
  group: THREE.Group;
  material: THREE.MeshBasicMaterial;
  light: THREE.PointLight;
  note: string;
  visits: number;
  pulseTimer: number;
};
type AlpeccaEnvironmentRoomMemory = {
  observations: number;
  online: boolean;
  lastAction: string;
  lastSource: string;
  lastSeen: string;
  lastQuestion: string;
  confidence: number;
};
type AlpeccaIdeaObject = {
  id: string;
  roomId: string;
  label: string;
  kind: "note" | "marker" | "spark" | "question" | "prototype";
  group: THREE.Group;
  material: THREE.MeshBasicMaterial;
  light: THREE.PointLight;
  life: number;
  pulseTimer: number;
};
type AlpeccaEnvironmentModelNode = {
  roomId: string;
  material: THREE.MeshBasicMaterial;
  railMaterial: THREE.MeshBasicMaterial;
  mesh: THREE.Mesh<THREE.BoxGeometry, THREE.MeshBasicMaterial>;
  rail: THREE.Mesh<THREE.BoxGeometry, THREE.MeshBasicMaterial>;
  light: THREE.PointLight;
};
type AlpeccaEnvironmentModel = {
  group: THREE.Group;
  nodes: Map<string, AlpeccaEnvironmentModelNode>;
  core: THREE.Mesh<THREE.OctahedronGeometry, THREE.MeshBasicMaterial>;
  coreMaterial: THREE.MeshBasicMaterial;
  light: THREE.PointLight;
  pulseTimer: number;
  activeRoomId: string;
};
type AlpeccaSelfMirror = {
  group: THREE.Group;
  surfaceMaterial: THREE.MeshBasicMaterial;
  reflection: THREE.Mesh<THREE.PlaneGeometry, THREE.MeshBasicMaterial>;
  signalMaterial: THREE.MeshBasicMaterial;
  critiqueBars: THREE.Mesh<THREE.BoxGeometry, THREE.MeshBasicMaterial>[];
  light: THREE.PointLight;
  pulseTimer: number;
  reviewTimer: number;
  cooldown: number;
  recursiveDepth: number;
  note: string;
};
type AlpeccaIdentityConsole = {
  group: THREE.Group;
  core: THREE.Mesh<THREE.OctahedronGeometry, THREE.MeshBasicMaterial>;
  coreMaterial: THREE.MeshBasicMaterial;
  slotMaterials: THREE.MeshBasicMaterial[];
  light: THREE.PointLight;
  pulseTimer: number;
  readIndex: number;
};
type AlpeccaAppMemory = {
  entries: number;
  returns: number;
  recursiveDepth: number;
  selfAudits: number;
  improvementRuns: number;
  curiositySweeps: number;
  identityReflections: number;
  clarityFeedbacks: number;
  visualCalmMode: boolean;
  hudMode: "auto" | "minimal" | "full";
  pendingReturn: boolean;
  lastPath: string;
  note: string;
  journal: string[];
  identityNotes: string[];
  activeIdentityQuestion: string;
  lastIdentityReflection: string;
  activeImprovementLayer: string;
  activeImprovementRoom: string;
  activeImprovementNote: string;
  lastImprovementResult: string;
  environmentRooms: Record<string, AlpeccaEnvironmentRoomMemory>;
  lastCuriosityRoom: string;
  lastCuriosityNote: string;
  lastClarityNote: string;
  pose: {
    environment: "void" | "hq";
    roomId: string;
    x: number;
    z: number;
    yaw: number;
    updatedAt: number;
  } | null;
};
type AlpeccaAgiJournal = {
  group: THREE.Group;
  coverMaterial: THREE.MeshBasicMaterial;
  pageMaterial: THREE.MeshBasicMaterial;
  lineMaterials: THREE.MeshBasicMaterial[];
  light: THREE.PointLight;
  pulseTimer: number;
  readIndex: number;
};
type AlpeccaImprovementQueue = {
  group: THREE.Group;
  core: THREE.Mesh<THREE.OctahedronGeometry, THREE.MeshBasicMaterial>;
  coreMaterial: THREE.MeshBasicMaterial;
  slotMaterials: Map<string, THREE.MeshBasicMaterial>;
  railMaterials: Map<string, THREE.MeshBasicMaterial>;
  light: THREE.PointLight;
  pulseTimer: number;
};
type AlpeccaAgiLayer = {
  id: string;
  name: string;
  roomId: string;
  featureId: string;
  description: string;
  prompt: string;
  color: string;
  node: THREE.Mesh<THREE.SphereGeometry, THREE.MeshBasicMaterial>;
  rail: THREE.Mesh<THREE.BoxGeometry, THREE.MeshBasicMaterial>;
  material: THREE.MeshBasicMaterial;
  light: THREE.PointLight;
  pulseTimer: number;
};
type AlpeccaHomeSystem = {
  id: string;
  kind: "lamp" | "plant";
  roomId: string;
  label: string;
  root: THREE.Object3D;
  item?: Interactable;
  signalMaterial?: THREE.MeshBasicMaterial;
  signalLight?: THREE.PointLight;
  pulseTimer: number;
  cooldown: number;
};
type AlpeccaAwareDoor = {
  name: string;
  root: THREE.Group;
  item: Interactable;
  roomId: string;
  signalMaterial: THREE.MeshBasicMaterial;
  signalLight: THREE.PointLight;
  autoTimer: number;
  openedByAlpecca: boolean;
};
type AlpeccaSystemId =
  | "overview"
  | "internals"
  | "self"
  | "devices"
  | "senses"
  | "voice"
  | "studio"
  | "observatory"
  | "memory"
  | "journal"
  | "soul"
  | "growth"
  | "files"
  | "games"
  | "mindscape"
  | "runtime";
type AlpeccaRouteGuide = {
  hall: THREE.Vector3;
  door: THREE.Vector3;
  approach: THREE.Vector3;
};
type Interactable = {
  id: string;
  label: string;
  root: THREE.Object3D;
  range: number;
  type: "toggle" | "collect" | "momentary";
  active?: boolean;
  collected?: boolean;
  onUse: (item: Interactable) => string;
  update?: (dt: number, item: Interactable) => void;
};

const app = document.querySelector<HTMLDivElement>("#app");
if (!app) throw new Error("Missing #app");

const hud = document.createElement("div");
hud.className = "hud";
hud.innerHTML = `
  <div class="topbar">
    <div class="objective">Initializing prototype environment</div>
    <div class="counter"><span id="found">0</span>/5</div>
  </div>
  <div id="hudChips" class="hud-chips">
    <button id="chipMission" type="button" data-expands="topbar" aria-expanded="false">0/5</button>
    <button id="chipRoom" type="button" data-expands="roomPanel" aria-expanded="false">Entry Hall</button>
    <button id="chipLoop" type="button" data-expands="livingState" aria-expanded="false" data-tone="idle">
      <i class="chip-dot" aria-hidden="true"></i><span id="chipLoopText">Loop</span><b id="chipPressureBar" aria-hidden="true"></b>
    </button>
  </div>
  <div id="roomPanel" class="room-panel">
    <span id="roomName">Entry Hall</span>
    <small id="roomPurpose">Move through the house to inspect each workspace.</small>
    <i id="roomStatus">Offline</i>
  </div>
  <div id="alpeccaActivity" class="activity-pill">Alpecca is orienting in the HQ.</div>
  <div id="alpeccaLivingState" class="living-state">
    <span>Living Loop</span>
    <strong id="alpeccaLivingIntent">Waiting</strong>
    <small id="alpeccaLivingQuestion">She is gathering grounded context before asking herself the next question.</small>
    <div id="alpeccaMemoryPressure" class="memory-pressure" data-pressure="unavailable" title="Working-memory telemetry is unavailable">
      <span>Working Memory</span>
      <em id="alpeccaMemoryPressureLabel">Unavailable</em>
      <i aria-hidden="true"><b id="alpeccaMemoryPressureBar"></b></i>
    </div>
  </div>
  <div id="message" class="message">Click to enter the house</div>
  <div id="prompt" class="prompt hidden"></div>
  <div id="perf" class="perf hidden"></div>
  <div id="alpeccaSourcePanel" class="source-panel">
    <div class="source-head">
      <span>Alpecca Source</span>
      <span id="alpeccaMoodReadout">offline</span>
    </div>
    <div id="alpeccaMoodBars" class="mood-bars"></div>
    <div class="source-actions">
      <button type="button" data-feature="self">Self</button>
      <button type="button" data-feature="memory">Memory</button>
      <button type="button" data-feature="journal">Journal</button>
      <button type="button" data-feature="studio">Studio</button>
      <button type="button" data-feature="home">Home</button>
    </div>
    <div class="source-actions source-nav">
      <button type="button" data-nav="mindscape">Mindscape</button>
      <button type="button" data-nav="voice">Voice</button>
      <button type="button" data-nav="tools">Tools</button>
    </div>
    <button id="openAlpeccaSource" class="source-open" type="button">Open Systems</button>
  </div>
  <button id="sourceChip" class="source-chip" type="button" data-expands="sourcePanel" aria-expanded="false" aria-label="Alpecca status"><span id="sourceChipMood">offline</span></button>
  <form id="alpeccaChat" class="alpecca-chat hidden" autocomplete="off">
    <div class="chat-status">
      <div class="chat-profile">
        <div id="alpeccaProfileAvatar" class="profile-avatar" aria-hidden="true">
          <span id="alpeccaProfileMouth" class="profile-mouth"></span>
        </div>
        <div>
          <span>Alpecca</span>
          <small id="alpeccaProfileState">offline</small>
          <em id="alpeccaProfileConnection">AI Offline</em>
        </div>
      </div>
      <button id="chatClose" type="button" aria-label="Close Alpecca chat">x</button>
    </div>
    <div class="chat-profile-meta">
      <span id="alpeccaProfileMode">Listening</span>
      <small id="alpeccaProfileSeen">Watching the room...</small>
    </div>
    <div class="voice-strip">
      <div>
        <span id="alpeccaVoiceIdentity">Alpecca's voice</span>
        <small id="alpeccaVoiceModulation">Original voice present</small>
      </div>
      <button type="button" data-hear-voice>Hear voice</button>
    </div>
    <nav class="hot-tabs" aria-label="Alpecca hot tabs">
      <button type="button" data-feature="self">Self</button>
      <button type="button" data-feature="memory">Memory</button>
      <button type="button" data-feature="journal">Journal</button>
      <button type="button" data-feature="studio">Studio</button>
      <button type="button" data-feature="home">Home</button>
      <button type="button" data-ask-room>Ask This Room</button>
      <button type="button" data-doctor>Doctor</button>
      <button type="button" data-self-review>Self Review</button>
      <button type="button" data-review-replies>Review Replies</button>
      <button type="button" data-improvement-queue>Queue</button>
      <button type="button" data-world-tick>Living Loop</button>
      <button type="button" data-system-open="observatory">Observatory</button>
      <button type="button" data-system-open="self">State</button>
      <button type="button" data-open-systems>Systems</button>
    </nav>
    <div id="alpeccaChatLine" class="chat-line">Ask Alpecca about the HQ, her memory, or the room you are standing in.</div>
    <div id="alpeccaInteractionLog" class="interaction-log" aria-live="polite"></div>
    <div class="source-art-card">
      <div class="source-art-head">
        <span id="alpeccaSourceArtLabel">Source Art</span>
        <small id="alpeccaSourceArtHint">Animation reference</small>
      </div>
      <div id="alpeccaSourceArtImage" class="source-art-image" aria-hidden="true"></div>
    </div>
    <div class="chat-row">
      <div class="chat-tools" role="group" aria-label="Voice and camera controls">
        <button id="alpeccaPushToTalk" type="button" title="Start push-to-talk" aria-label="Start push-to-talk" aria-pressed="false">
          <span data-mic-idle aria-hidden="true">&#127908;</span><span data-mic-recording aria-hidden="true">&#9632;</span>
        </button>
        <button id="alpeccaCameraOpen" type="button" title="Open camera" aria-label="Open camera" aria-pressed="false">
          <span aria-hidden="true">&#128247;</span>
        </button>
        <button id="alpeccaSpokenReplies" type="button" title="Mute spoken replies" aria-label="Mute spoken replies" aria-pressed="true">
          <span data-speech-on aria-hidden="true">&#128266;</span><span data-speech-off aria-hidden="true">&#128263;</span>
        </button>
      </div>
      <input id="alpeccaChatInput" maxlength="180" placeholder="Message Alpecca..." />
      <button id="alpeccaChatSend" type="submit">Send</button>
    </div>
    <div id="alpeccaCameraPreview" class="chat-camera hidden" role="dialog" aria-label="Camera preview">
      <video id="alpeccaCameraVideo" autoplay muted playsinline></video>
      <div class="chat-camera-actions">
        <button type="button" data-camera-cancel>Cancel</button>
        <button type="button" data-camera-send>Send frame</button>
      </div>
    </div>
  </form>
  <div id="alpeccaWorkshop" class="workshop-overlay hidden" role="dialog" aria-modal="true" aria-label="Alpecca improvement workshop">
    <div class="workshop-panel">
      <div class="workshop-head">
        <div class="workshop-title">
          <strong>Workshop &middot; Improvement Queue</strong>
          <small id="workshopSummary">Loading proposals...</small>
          <small id="workshopTrialStatus" class="workshop-trial-status"></small>
          <div id="workshopReviewDecision" class="workshop-review-decision hidden" aria-live="polite"></div>
        </div>
        <div class="workshop-head-actions">
          <button type="button" data-workshop-run title="Run runtime + behavior self-review">Run Review</button>
          <button type="button" data-workshop-compact title="Close duplicate open cards">Compact</button>
          <button type="button" data-workshop-handoff title="Copy a bounded Codex/Claude/ChatGPT handoff">Handoff</button>
          <button type="button" data-workshop-refresh title="Reload the queue">Refresh</button>
          <button type="button" data-workshop-close aria-label="Close workshop">x</button>
        </div>
      </div>
      <div id="workshopList" class="workshop-list" aria-live="polite"></div>
      <div class="workshop-foot">
        <small>Alpecca proposes; you approve. Accepting an <b>ask-first</b> or <b>never-auto</b> card needs your explicit approval. A never-auto card is approved as a <b>plan only</b> &mdash; she never acts on it unassisted, and she makes no autonomous code edits.</small>
      </div>
    </div>
  </div>
  <div id="alpeccaSystems" class="systems-overlay hidden" role="dialog" aria-modal="true" aria-label="Alpecca systems center">
    <div class="systems-panel">
      <header class="systems-head">
        <div class="systems-title">
          <strong>Alpecca Systems</strong>
          <small id="alpeccaSystemsStatus">Live controls inside the Void Prototype</small>
        </div>
        <div class="systems-head-actions">
          <button type="button" data-systems-refresh title="Refresh current system">Refresh</button>
          <button type="button" data-systems-close aria-label="Close systems center">x</button>
        </div>
      </header>
      <div class="systems-shell">
        <nav id="alpeccaSystemsNav" class="systems-nav" aria-label="Alpecca systems">
          <div class="systems-nav-group"><span>Core</span>
            <button type="button" data-system-id="overview">Overview</button>
            <button type="button" data-system-id="internals">Internals</button>
            <button type="button" data-system-id="self">Self</button>
            <button type="button" data-system-id="soul">Soul</button>
          </div>
          <div class="systems-nav-group"><span>Experience</span>
            <button type="button" data-system-id="senses">Senses</button>
            <button type="button" data-system-id="voice">Voice</button>
            <button type="button" data-system-id="observatory">Observatory</button>
          </div>
          <div class="systems-nav-group"><span>Records</span>
            <button type="button" data-system-id="memory">Memory</button>
            <button type="button" data-system-id="journal">Journal</button>
            <button type="button" data-system-id="mindscape">Mindscape</button>
            <button type="button" data-system-id="files">Files</button>
          </div>
          <div class="systems-nav-group"><span>Actions</span>
            <button type="button" data-system-id="studio">Studio</button>
            <button type="button" data-system-id="growth">Growth</button>
            <button type="button" data-system-id="games">Games</button>
          </div>
          <div class="systems-nav-group"><span>System</span>
            <button type="button" data-system-id="devices">Devices</button>
            <button type="button" data-system-id="runtime">Runtime</button>
          </div>
        </nav>
        <section class="systems-workspace">
          <div id="alpeccaSystemsAffect" class="systems-affect" aria-label="Live emotion state"></div>
          <div id="alpeccaSystemsNotice" class="systems-notice hidden" role="status"></div>
          <div id="alpeccaSystemsBody" class="systems-body" aria-live="polite"></div>
        </section>
      </div>
    </div>
  </div>
  <div id="moveStick" class="move-stick" aria-label="Move">
    <div id="moveKnob" class="move-knob"></div>
  </div>
  <button id="touchInteract" class="touch-interact" aria-label="Interact">E</button>
  <button id="menuButton" class="menu-button" aria-label="Open menu">?</button>
  <div id="menu" class="menu hidden">
    <strong>Alpecca Void</strong>
    <span class="master-plan-status">Void Prototype: embodied home and systems</span>
    <span id="environmentModeLabel">Environment: Void Prototype</span>
    <button id="environmentModeToggle" type="button">Enter the AI Office HQ</button>
    <span id="masterPlanStageLabel" class="master-plan-status">Master plan: Phase 8 RSI verified; operational soak pending; Phase 9 active</span>
    <span id="alpeccaAssetModeLabel" class="master-plan-status">Art assets: Local fallback</span>
    <span>WASD move</span>
    <span>Click game to lock mouse</span>
    <span>Move mouse to look</span>
    <span>Mouse wheel looks up/down</span>
    <span>E interact</span>
    <span>F performance meter</span>
    <span id="alpeccaAiStatus">Alpecca AI: Offline</span>
    <span id="alpeccaSpriteStatus">Alpecca sprites: Loading</span>
    <button id="viewModeToggle" type="button">View: First-person</button>
    <button id="calmModeToggle" type="button">Calm mode: On</button>
    <button id="hudModeToggle" type="button">HUD: Auto</button>
    <button id="embodimentToggle" type="button">Body: 2D sprite</button>
    <span id="embodimentStatus" class="master-plan-status">3D body: experimental, not loaded</span>
    <button id="profileQaToggle" type="button">Profile QA</button>
    <div id="profileQaPanel" class="qa-panel hidden">
      <button type="button" data-profile-mode="listening">Listen</button>
      <button type="button" data-profile-mode="thinking">Think</button>
      <button type="button" data-profile-mode="talking">Talk</button>
      <button type="button" data-profile-mood="happy">Happy</button>
      <button type="button" data-profile-mood="worried">Worried</button>
      <button type="button" data-profile-mood="sleepy">Sleepy</button>
      <button type="button" data-profile-mood="angry">Angry</button>
    </div>
    <button id="spriteQaToggle" type="button">Sprite QA</button>
    <div id="spriteQaPanel" class="qa-panel hidden">
      <button type="button" data-sprite-state="idleDown">Idle</button>
      <button type="button" data-sprite-state="talkDown">Talk</button>
      <button type="button" data-sprite-state="waveDown">Wave</button>
      <button type="button" data-sprite-state="kneel">Kneel</button>
      <button type="button" data-sprite-state="walkDown">Walk Down</button>
      <button type="button" data-sprite-state="walkUp">Walk Up</button>
      <button type="button" data-sprite-state="walkSide">Walk Right</button>
      <button type="button" data-sprite-state="walkLeft">Walk Left</button>
    </div>
    <button id="stageQaToggle" type="button">Stage QA</button>
    <button id="cylinderQaToggle" type="button">Cylinder QA</button>
    <label class="token-row">
      <span>Backend</span>
      <input id="alpeccaBackend" type="url" placeholder="live app URL" autocomplete="off" spellcheck="false" aria-label="Alpecca backend URL" />
    </label>
    <span>Shift walk faster</span>
    <span>Esc unlocks mouse</span>
  </div>
  <div class="crosshair" aria-hidden="true"></div>
`;
app.appendChild(hud);

const objectiveEl = hud.querySelector<HTMLDivElement>(".objective")!;
const promptEl = hud.querySelector<HTMLDivElement>("#prompt")!;
const messageEl = hud.querySelector<HTMLDivElement>("#message")!;
const perfEl = hud.querySelector<HTMLDivElement>("#perf")!;
const alpeccaActivityEl = hud.querySelector<HTMLDivElement>("#alpeccaActivity")!;
const alpeccaLivingStateEl = hud.querySelector<HTMLDivElement>("#alpeccaLivingState")!;
const alpeccaLivingIntentEl = hud.querySelector<HTMLElement>("#alpeccaLivingIntent")!;
const alpeccaLivingQuestionEl = hud.querySelector<HTMLElement>("#alpeccaLivingQuestion")!;
const alpeccaSourcePanel = hud.querySelector<HTMLDivElement>("#alpeccaSourcePanel")!;
const alpeccaMoodReadout = hud.querySelector<HTMLSpanElement>("#alpeccaMoodReadout")!;
const alpeccaMoodBars = hud.querySelector<HTMLDivElement>("#alpeccaMoodBars")!;
const openAlpeccaSourceButton = hud.querySelector<HTMLButtonElement>("#openAlpeccaSource")!;
const alpeccaChat = hud.querySelector<HTMLFormElement>("#alpeccaChat")!;
const alpeccaChatInput = hud.querySelector<HTMLInputElement>("#alpeccaChatInput")!;
const alpeccaChatSend = hud.querySelector<HTMLButtonElement>("#alpeccaChatSend")!;
const alpeccaPushToTalkButton = hud.querySelector<HTMLButtonElement>("#alpeccaPushToTalk")!;
const alpeccaCameraOpenButton = hud.querySelector<HTMLButtonElement>("#alpeccaCameraOpen")!;
const alpeccaSpokenRepliesButton = hud.querySelector<HTMLButtonElement>("#alpeccaSpokenReplies")!;
const alpeccaCameraPreview = hud.querySelector<HTMLDivElement>("#alpeccaCameraPreview")!;
const alpeccaCameraVideo = hud.querySelector<HTMLVideoElement>("#alpeccaCameraVideo")!;
const alpeccaProfileAvatar = hud.querySelector<HTMLDivElement>("#alpeccaProfileAvatar")!;
const alpeccaProfileMouth = hud.querySelector<HTMLSpanElement>("#alpeccaProfileMouth")!;
const alpeccaProfileState = hud.querySelector<HTMLElement>("#alpeccaProfileState")!;
const alpeccaProfileConnection = hud.querySelector<HTMLElement>("#alpeccaProfileConnection")!;
const alpeccaProfileModeEl = hud.querySelector<HTMLSpanElement>("#alpeccaProfileMode")!;
const alpeccaProfileSeenEl = hud.querySelector<HTMLElement>("#alpeccaProfileSeen")!;
const alpeccaVoiceIdentityEl = hud.querySelector<HTMLSpanElement>("#alpeccaVoiceIdentity")!;
const alpeccaVoiceModulationEl = hud.querySelector<HTMLElement>("#alpeccaVoiceModulation")!;
const alpeccaVoiceButtons = Array.from(hud.querySelectorAll<HTMLButtonElement>("[data-voice-preview]"));
alpeccaVoiceButtons.forEach((button) => {
  button.title = `Preview Alpecca ${button.dataset.voicePreview || "current"} voice modulation`;
});
const alpeccaChatLine = hud.querySelector<HTMLDivElement>("#alpeccaChatLine")!;
const alpeccaInteractionLogEl = hud.querySelector<HTMLDivElement>("#alpeccaInteractionLog")!;
const alpeccaSourceArtLabel = hud.querySelector<HTMLSpanElement>("#alpeccaSourceArtLabel")!;
const alpeccaSourceArtHint = hud.querySelector<HTMLElement>("#alpeccaSourceArtHint")!;
const alpeccaSourceArtImage = hud.querySelector<HTMLDivElement>("#alpeccaSourceArtImage")!;
const chatClose = hud.querySelector<HTMLButtonElement>("#chatClose")!;
const alpeccaAiStatusEl = hud.querySelector<HTMLSpanElement>("#alpeccaAiStatus")!;
const alpeccaSpriteStatusEl = hud.querySelector<HTMLSpanElement>("#alpeccaSpriteStatus")!;
const alpeccaBackendInput = hud.querySelector<HTMLInputElement>("#alpeccaBackend")!;
const foundEl = hud.querySelector<HTMLSpanElement>("#found")!;
const roomPanel = hud.querySelector<HTMLDivElement>("#roomPanel")!;
const roomNameEl = hud.querySelector<HTMLSpanElement>("#roomName")!;
const roomPurposeEl = hud.querySelector<HTMLElement>("#roomPurpose")!;
const roomStatusEl = hud.querySelector<HTMLElement>("#roomStatus")!;
const alpeccaMemoryPressureEl = hud.querySelector<HTMLDivElement>("#alpeccaMemoryPressure")!;
const alpeccaMemoryPressureLabel = hud.querySelector<HTMLElement>("#alpeccaMemoryPressureLabel")!;
const alpeccaMemoryPressureBar = hud.querySelector<HTMLElement>("#alpeccaMemoryPressureBar")!;
const menu = hud.querySelector<HTMLDivElement>("#menu")!;
const menuButton = hud.querySelector<HTMLButtonElement>("#menuButton")!;
const environmentModeLabel = hud.querySelector<HTMLSpanElement>("#environmentModeLabel")!;
const environmentModeToggle = hud.querySelector<HTMLButtonElement>("#environmentModeToggle")!;

// Select the scene before any control asks which environment is active. Keeping
// this above the first isPrototypeMode() call matters in unbundled dev mode,
// where const temporal-dead-zone semantics are not lowered by the build.
const currentEnvironmentMode: "prototype" | "hq" = (() => {
  try {
    return new URL(window.location.href).searchParams.get("environment") === "hq" ? "hq" : "prototype";
  } catch {
    return "prototype";
  }
})();

function isPrototypeMode() {
  return currentEnvironmentMode === "prototype";
}

environmentModeToggle.textContent = isPrototypeMode() ? "Enter the AI Office HQ" : "Return to the Void";
environmentModeToggle.addEventListener("click", (event) => {
  event.stopPropagation();
  // Void <-> Office HQ is a navigation so the scene rebuilds with the right
  // rooms; ?environment=hq enters the office, no param returns to the void.
  const target = new URL(window.location.href);
  if (isPrototypeMode()) target.searchParams.set("environment", "hq");
  else target.searchParams.delete("environment");
  window.location.assign(target.toString());
});
const masterPlanStageLabel = hud.querySelector<HTMLSpanElement>("#masterPlanStageLabel")!;
const alpeccaAssetModeLabel = hud.querySelector<HTMLSpanElement>("#alpeccaAssetModeLabel")!;
const calmModeToggle = hud.querySelector<HTMLButtonElement>("#calmModeToggle")!;
const profileQaToggle = hud.querySelector<HTMLButtonElement>("#profileQaToggle")!;
const profileQaPanel = hud.querySelector<HTMLDivElement>("#profileQaPanel")!;
const spriteQaToggle = hud.querySelector<HTMLButtonElement>("#spriteQaToggle")!;
const spriteQaPanel = hud.querySelector<HTMLDivElement>("#spriteQaPanel")!;
const stageQaToggle = hud.querySelector<HTMLButtonElement>("#stageQaToggle")!;
const cylinderQaToggle = hud.querySelector<HTMLButtonElement>("#cylinderQaToggle")!;
const moveStick = hud.querySelector<HTMLDivElement>("#moveStick")!;
const moveKnob = hud.querySelector<HTMLDivElement>("#moveKnob")!;
const touchInteract = hud.querySelector<HTMLButtonElement>("#touchInteract")!;
const alpeccaWorkshop = hud.querySelector<HTMLDivElement>("#alpeccaWorkshop")!;
const workshopList = hud.querySelector<HTMLDivElement>("#workshopList")!;
const workshopSummary = hud.querySelector<HTMLElement>("#workshopSummary")!;
const workshopTrialStatus = hud.querySelector<HTMLElement>("#workshopTrialStatus")!;
const workshopReviewDecision = hud.querySelector<HTMLDivElement>("#workshopReviewDecision")!;
const alpeccaSystems = hud.querySelector<HTMLDivElement>("#alpeccaSystems")!;
const alpeccaSystemsNav = hud.querySelector<HTMLElement>("#alpeccaSystemsNav")!;
const alpeccaSystemsStatus = hud.querySelector<HTMLElement>("#alpeccaSystemsStatus")!;
const alpeccaSystemsNotice = hud.querySelector<HTMLDivElement>("#alpeccaSystemsNotice")!;
const alpeccaSystemsBody = hud.querySelector<HTMLDivElement>("#alpeccaSystemsBody")!;
const alpeccaSystemsAffect = hud.querySelector<HTMLDivElement>("#alpeccaSystemsAffect")!;
const hudChipsEl = hud.querySelector<HTMLDivElement>("#hudChips")!;
const chipMission = hud.querySelector<HTMLButtonElement>("#chipMission")!;
const chipRoom = hud.querySelector<HTMLButtonElement>("#chipRoom")!;
const chipLoop = hud.querySelector<HTMLButtonElement>("#chipLoop")!;
const chipLoopText = hud.querySelector<HTMLSpanElement>("#chipLoopText")!;
const chipPressureBar = hud.querySelector<HTMLElement>("#chipPressureBar")!;
const sourceChip = hud.querySelector<HTMLButtonElement>("#sourceChip")!;
const sourceChipMood = hud.querySelector<HTMLSpanElement>("#sourceChipMood")!;
const hudModeToggle = hud.querySelector<HTMLButtonElement>("#hudModeToggle")!;
const viewModeToggle = hud.querySelector<HTMLButtonElement>("#viewModeToggle")!;
const embodimentToggle = hud.querySelector<HTMLButtonElement>("#embodimentToggle")!;
const embodimentStatus = hud.querySelector<HTMLSpanElement>("#embodimentStatus")!;
const topbarEl = hud.querySelector<HTMLDivElement>(".topbar")!;

// Public identity metadata only. Backend authorization comes from an HttpOnly
// session cookie and must never treat this stable value as a bearer credential.
const alpeccaPublicIdentity = "wLbIoOwoOJHQR4QQ_goptIa2";
const alpeccaLegacyAuthorizationQueryParams = ["token", "access_token", "alpeccaToken", "alpecca_token"] as const;

try {
  const launchUrl = new URL(window.location.href);
  const hadLegacyAuthorization = alpeccaLegacyAuthorizationQueryParams.some((name) => launchUrl.searchParams.has(name));
  for (const name of alpeccaLegacyAuthorizationQueryParams) launchUrl.searchParams.delete(name);
  if (hadLegacyAuthorization) window.history.replaceState(window.history.state, "", launchUrl.toString());
} catch {
  // A malformed launch URL is handled by the normal backend URL fallback.
}
localStorage.removeItem("alpeccaAccessToken");

const scene = new THREE.Scene();
scene.background = new THREE.Color("#aebfc4");
scene.fog = new THREE.Fog("#aebfc4", 22, 46);

const camera = new THREE.PerspectiveCamera(68, window.innerWidth / window.innerHeight, 0.05, 80);
camera.position.set(0.12, 1.55, 0.28);
const orthographicCamera = new THREE.OrthographicCamera(-8, 8, 6, -6, 0.1, 80);
const orthographicTarget = new THREE.Vector3(0, 0.7, 0);
const alpeccaViewModeStorageKey = "alpeccaVoidViewMode";
const requestedAlpeccaView = urlParamValue(["view", "camera"]).toLowerCase();
let alpeccaViewMode: "first-person" | "orthographic" =
  requestedAlpeccaView === "orthographic" || localStorage.getItem(alpeccaViewModeStorageKey) === "orthographic"
    ? "orthographic"
    : "first-person";
let alpeccaOrthographicZoom = 1;

function updateOrthographicCamera() {
  const aspect = Math.max(0.35, window.innerWidth / Math.max(1, window.innerHeight));
  const halfHeight = Math.max(6.4, 6.4 / aspect);
  orthographicCamera.left = -halfHeight * aspect;
  orthographicCamera.right = halfHeight * aspect;
  orthographicCamera.top = halfHeight;
  orthographicCamera.bottom = -halfHeight;
  orthographicCamera.position.set(8.6, 11.5, 9.6);
  orthographicCamera.lookAt(orthographicTarget);
  orthographicCamera.zoom = alpeccaOrthographicZoom;
  orthographicCamera.updateProjectionMatrix();
}

function alpeccaPresentationCamera() {
  return alpeccaViewMode === "orthographic" ? orthographicCamera : camera;
}

updateOrthographicCamera();

const renderer = new THREE.WebGLRenderer({ antialias: false, powerPreference: "high-performance" });
function targetRenderPixelRatio() {
  const viewportCap = window.innerWidth < 900 ? 1.12 : 1.24;
  return Math.min(window.devicePixelRatio || 1, viewportCap);
}

renderer.setPixelRatio(targetRenderPixelRatio());
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.shadowMap.enabled = false;
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.03;
renderer.domElement.tabIndex = 0;
app.appendChild(renderer.domElement);

function setAlpeccaViewMode(mode: "first-person" | "orthographic", announce = true) {
  alpeccaViewMode = mode;
  localStorage.setItem(alpeccaViewModeStorageKey, mode);
  document.body.dataset.viewMode = mode;
  viewModeToggle.textContent = mode === "orthographic" ? "View: Orthographic" : "View: First-person";
  viewModeToggle.setAttribute("aria-pressed", String(mode === "orthographic"));
  keys.clear();
  resetMoveStick();
  if (mode === "orthographic") {
    if (document.pointerLockElement === renderer.domElement) document.exitPointerLock();
    updateOrthographicCamera();
  }
  if (announce) {
    showMessage(
      mode === "orthographic"
        ? "Orthographic overview active. Use the menu to return to first-person."
        : "First-person view active.",
      3.4,
    );
  }
}

const clock = new THREE.Clock();
const raycaster = new THREE.Raycaster();
const centerRay = new THREE.Vector2(0, 0);
const targetWorldPosition = new THREE.Vector3();
const alpeccaToTarget = new THREE.Vector3();
const alpeccaToPlayer = new THREE.Vector3();
const alpeccaLastMove = new THREE.Vector3(0, 0, 1);
const alpeccaLastWorldMove = new THREE.Vector3(0, 0, 1);
const cameraForwardFlat = new THREE.Vector3();
const cameraRightFlat = new THREE.Vector3();
const alpeccaAvoidance = new THREE.Vector3();
const alpeccaCandidate = new THREE.Vector3();
const alpeccaSideStep = new THREE.Vector3();
const alpeccaMirrorLocal = new THREE.Vector3();
const alpeccaPresenceColor = new THREE.Color();
const alpeccaFloorColor = new THREE.Color();
const alpeccaSpritePlaneSize = 2.58;
const alpeccaSpriteDepthScale = 1;
const alpeccaStandingVisibleHeight = 1.70;
const alpeccaStandingPresentationScale = 1.12;
const alpeccaGroundClearance = 0.02;
const alpeccaCylinderBodyRadius = 0.72;
const alpeccaCylinderInteractionRadius = 1.62;
const alpeccaCylinderFarRadius = 2.72;
const alpeccaCylinderStageRadius = 0.92;
const alpeccaWalkFrameEpsilon = 0.001;
const alpeccaWalkFrameRate = 6.9;
const alpeccaWalkPlaybackMin = 5.1;
const alpeccaWalkPlaybackMax = 7.6;
const alpeccaWalkReferenceSpeed = 0.18;
const alpeccaWalkSecondsPerFrame = 1 / alpeccaWalkFrameRate;
const alpeccaDirectionDeadzone = 0.18;
const alpeccaDirectionDiagonalMin = 0.31;
const alpeccaDirectionHorizontalBias = 1.42;
const alpeccaWalkQaStates: AlpeccaAnimationName[] = [
  "walkDown",
  "walkUp",
  "walkSide",
  "walkLeft",
  "walkNortheast",
  "walkNorthwest",
  "walkSoutheast",
  "walkSouthwest",
];
const alpeccaWalkQaInterval = 3.9;
const keys = new Set<string>();
const walls: Wall[] = [];
const interactables: Interactable[] = [];
const interactableMeshes = new Map<string, Interactable>();
const interactableObjects: THREE.Object3D[] = [];
const alpeccaRoomDevices = new Map<string, AlpeccaRoomDevice>();
const alpeccaSourceTerminals = new Map<string, AlpeccaSourceTerminal>();
const alpeccaTerminalTargets = new Map<string, AlpeccaTerminalTarget>();
const alpeccaSourceGalleryPanels = new Map<string, AlpeccaSourceGalleryPanel>();
const alpeccaExpressionTextures = new Map<string, THREE.Texture>();
const alpeccaAvatarTextures = new Map<string, THREE.Texture>();
const alpeccaDetailPoints: AlpeccaDetailPoint[] = [];
const alpeccaMemoryTraces = new Map<string, AlpeccaMemoryTrace>();
const alpeccaHomeSystems: AlpeccaHomeSystem[] = [];
const alpeccaAwareDoors: AlpeccaAwareDoor[] = [];
const alpeccaAgiLayers: AlpeccaAgiLayer[] = [];
const alpeccaIdeaObjects: AlpeccaIdeaObject[] = [];
let alpeccaEnvironmentModel: AlpeccaEnvironmentModel | null = null;
let alpeccaSourceDashboard: AlpeccaSourceDashboard | null = null;
let alpeccaSelfMirror: AlpeccaSelfMirror | null = null;
let prototypePlayerSpotlight: THREE.SpotLight | null = null;
let alpeccaIdentityConsole: AlpeccaIdentityConsole | null = null;
let alpeccaCylinderQaGroup: THREE.Group | null = null;
let alpeccaCylinderMovementClamped = false;
const animatedProps: Array<(dt: number) => void> = [];
const playerRadius = 0.32;
const player = {
  yaw: 0,
  pitch: 0,
  velocity: new THREE.Vector3(),
  bob: 0,
};

window.__HOUSE_DEBUG__ = { camera, player };
window.__ALPECCA_RUNTIME__ = {
  ready: false,
  state: "boot",
  folder: "",
  artBaseUrl: "local",
  artAssetMode: "local-fallback",
  artManifestUrl: "/assets/alpecca_asset_sources.json",
  matrixAction: "idle",
  matrixAssetKey: "idle_eye_front_native_pending",
  matrixRequestedKey: "idle_eye_front_native_pending",
  matrixLoadedKey: "idle_eye_front_idleDown",
  matrixFallbackState: "idleDown",
  matrixFolder: "iso_idle_down_right",
  matrixFrameCount: 0,
  matrixSourceFamily: "iso",
  matrixApprovalStatus: "approved",
  matrixManifestStatus: "pending",
  matrixResolution: "local-fallback",
  matrixLayerPlan: "base-body+contact-shadow+depth-proxy+floor-reflection",
  matrixFootAnchor: "bottom-center",
  matrixContactFrames: "",
  matrixDepthProxy: "fallback-alpha-silhouette-plane",
  frameIndex: 0,
  frameCount: 0,
  moving: false,
  direction: "down",
  worldDirection: "down",
  screenDirection: "down",
  directionCandidate: "down",
  directionCandidateFrames: 0,
  billboardYaw: 0,
  groundYaw: 0,
  footContact: "idle",
  presence: 0,
  bodyLean: 0,
  mirrorReflection: 0,
  groundContact: 0,
  floorReflection: 0,
  animationLock: 0,
  dwell: 0,
  walkPause: 0,
  movementLoaded: 0,
  movementTotal: 0,
  movementMissing: [],
  animationLoaded: 0,
  animationTotal: 0,
  animationMissing: [],
  walkIntent: false,
  movedDistance: 0,
  walkPlaybackRate: alpeccaWalkFrameRate,
  walkSpeed: 0,
  intent: "idle",
  animationSourceFamily: "",
  animationSourceStatus: "approved",
  animationSourceFlagged: false,
  flipX: false,
  perceptionTarget: "",
  talking: false,
  mouthOpen: 0,
  profileMouthMode: "fallback-overlay",
  profileTalkFrame: "",
  voiceEngine: "",
  voiceName: "af_heart",
  voiceProfile: "af_heart_original_modulated",
  voicePreview: "current",
  voicePrimary: "content",
  voiceTempo: "measured",
  voiceRate: "100",
  voiceSpeed: "1",
  voiceStyle: "present",
  voiceWarmth: "",
  voiceBreath: "",
  voiceEmotionTimer: 0,
  voiceEmotionState: {},
  freedomAction: "",
  worldTickTimer: 0,
  worldTickInFlight: false,
  walkFrameRate: alpeccaWalkFrameRate,
  frameTime: 0,
  loopCount: 0,
  droppedFrames: 0,
  heightClass: "standing",
  standingScaleLocked: true,
  silhouetteWidth: 0,
  legWidthRatio: 0,
  profileMode: "listening",
  profileExpression: "",
  activeFeature: "",
  lastSeen: "",
  lastQuestion: "",
  ideaObjects: 0,
  debugLocked: false,
  debugLockState: "",
  scaleY: 1,
  spriteY: 0,
  strideX: 0,
  x: 0,
  z: 0,
  routeStep: "0/0",
  viewVertical: "eye",
  viewHorizontal: "front",
  viewMatrix: "eye_front",
  relativeYawDeg: 0,
  cameraPitchDeg: 0,
  viewVolumeZone: "far",
  viewVolumeProbe: "torso",
  viewVolumeDepth: 0,
  viewSampleY: 0.96,
  viewSector16: 0,
  viewSector16Key: "s00",
  cylinderRadius: alpeccaCylinderFarRadius,
  cylinderZone: "far-shell",
  cylinderPlayerAngleDeg: 0,
  cylinderPlayerDistance: 0,
  cylinderVerticalTier: "eye",
  cylinderMovementClamped: false,
  cylinderQaVisible: false,
  billboardMode: "volume-soft-billboard",
  billboardClampDeg: 24,
  stageRoom: "entry",
  stagePad: "Entry orientation stage",
  stageQaIssues: [],
  navClearance: "unchecked",
  renderCalls: 0,
  pixelRatio: targetRenderPixelRatio(),
};

let currentTarget: Interactable | null = null;
let activatedRooms = 0;
const activeRoomIds = new Set<string>();
let foundKeepsakes = 0;
let lastMessageTimer = 0;
let currentRoomId = "entry";
let roomPanelTimer = 0;
let targetPollTimer = 0;
let perfTimer = 0;
let perfFrames = 0;
let showPerf = false;
let perfAutoQaEnabled = false;
let isDraggingLook = false;
let pointerLockBlocked = false;
let lastMouse: { x: number; y: number } | null = null;
let edgeLook = { x: 0, y: 0, active: false };
let lastTouch: { x: number; y: number } | null = null;
let alpeccaInteractable: Interactable | null = null;
let virtualMove = { x: 0, z: 0 };
let movePointerId: number | null = null;
let alpeccaSocket: WebSocket | null = null;
let alpeccaAiStatus: AlpeccaAiStatus = "offline";
let alpeccaAiRetryTimer = 0;
let alpeccaAiProbeTimer: number | null = null;
let alpeccaAiMood = "offline";
let alpeccaAiState: Record<string, number> = {};
let alpeccaAiLlmOnline = false;
let alpeccaAiModelUse: AlpeccaModelUse = {};
let alpeccaAiAwaitingReply = false;
let alpeccaAiReplyStartedAt = 0;
let alpeccaAiSlowReplyNoticeShown = false;
let alpeccaAiExtendedReplyNoticeShown = false;
let alpeccaAiPendingPlayerRequestId = "";
let alpeccaAiRequestSequence = 0;
let alpeccaAiLastPlayerMessage = "";
const alpeccaAiCompletedRequestIds = new Set<string>();
let alpeccaPendingSourceRef: AlpeccaSourceRef | null = null;
let alpeccaCapabilityConnection: AlpeccaCapabilityConnection | null = null;
const alpeccaCapabilityLeases = new Map<AlpeccaCapabilityPurpose, AlpeccaCapabilityLease>();
let alpeccaAiPendingCapabilityLease: { requestId: string; lease: AlpeccaCapabilityLease } | null = null;
let alpeccaCapabilityChannelRequest: AbortController | null = null;
const ALPECCA_AI_SLOW_REPLY_MS = 12000;
const ALPECCA_AI_PLAYER_REPLY_NOTICE_MS = 35000;
const ALPECCA_AI_COMPLETED_REQUEST_LIMIT = 64;
let alpeccaPlayerChatQuietTimer = 0;
let alpeccaAiOfflineNoticeShown = false;
let alpeccaAiServerReachable = false;
let alpeccaLiveAttentionTimer = 0;
let alpeccaVoiceAudio: HTMLAudioElement | null = null;
let alpeccaVoiceObjectUrl = "";
let alpeccaVoiceLastText = "";
let alpeccaVoiceAudioContext: AudioContext | null = null;
let alpeccaVoicePlaybackUnlocked = false;
let alpeccaVoiceSessionState: VoiceSessionState = "idle";
const alpeccaSpokenRepliesStorageKey = "alpeccaHouseSpokenReplies";
let alpeccaSpokenRepliesEnabled = localStorage.getItem(alpeccaSpokenRepliesStorageKey) !== "off";
const ALPECCA_PUSH_TO_TALK_MAX_MS = 60_000;
const ALPECCA_TTS_REQUEST_TIMEOUT_MS = 45_000;
const ALPECCA_DRIVE_REQUEST_TIMEOUT_MS = 12_000;
let alpeccaPushToTalkRecorder: MediaRecorder | null = null;
let alpeccaPushToTalkStream: MediaStream | null = null;
let alpeccaPushToTalkChunks: Blob[] = [];
let alpeccaPushToTalkSequence = 0;
let alpeccaPushToTalkStopTimer: number | null = null;
let alpeccaPushToTalkRequest: AbortController | null = null;
let alpeccaCameraStream: MediaStream | null = null;
let alpeccaCameraSequence = 0;
let alpeccaVoiceEngine = "";
let alpeccaVoiceName = "af_heart";
let alpeccaVoiceProfile = "af_heart_original_modulated";
let alpeccaVoicePreview = "current";
let alpeccaVoicePrimary = "content";
let alpeccaVoiceTempo = "measured";
let alpeccaVoiceRate = "100";
let alpeccaVoiceSpeed = "1";
let alpeccaVoiceStyle = "present";
let alpeccaVoiceWarmth = "";
let alpeccaVoiceBreath = "";
let alpeccaVoiceModulationStrength = "";
let alpeccaVoiceEmotionTimer = 0;
let alpeccaVoiceEmotionState: Record<string, number> = {};
type AlpeccaSpeechPriority = "reply" | "proactive" | "preview";

function setAlpeccaAvatarPlayback(active: boolean) {
  document.body.dataset.alpeccaTalking = String(active);
  alpeccaChat.classList.toggle("talking", active);
  if (!active) {
    alpecca.mouthOpen = 0;
    alpeccaProfileTalkFrame = "";
    alpeccaProfileTalkFrameKey = "";
    alpeccaProfileTalkFrameTier = -1;
    alpeccaProfileLastTalkFrameAt = 0;
    alpeccaProfileHeldExpression = undefined;
    alpeccaProfileMouth.style.opacity = "0";
    alpeccaProfileMouth.style.transform = "translateX(-50%) scale(1, 0.35)";
    if (alpecca.mouth && alpecca.mouthMaterial) {
      alpecca.mouth.visible = false;
      alpecca.mouthMaterial.opacity = 0;
      alpecca.mouth.scale.set(1, 0.28, 1);
      alpecca.mouth.position.y = -0.125;
    }
    if (alpecca.state === "talkDown") setAlpeccaAnimation("idleDown", true);
    document.body.dataset.alpeccaMouthOpen = "0";
  }
  alpeccaVrmEmbodiment?.setSpriteState(
    alpecca.state,
    alpecca.moving,
    active,
    false,
    alpecca.walkSpeed,
    alpeccaLastMove,
  );
}

const alpeccaAvatarPlaybackSignal = createVoiceAvatarPlaybackSignal({
  onChange: ({ talking, audio }) => {
    if (talking) {
      if (audio) alpeccaVoiceAudio = audio;
      setAlpeccaAvatarPlayback(true);
    }
    setAlpeccaProfileMode(talking ? "talking" : "listening", alpeccaActiveProfileFeature);
  },
  onMouthReset: () => setAlpeccaAvatarPlayback(false),
});

function setVisibleAlpeccaVoiceSession(state: VoiceSessionState) {
  alpeccaVoiceSessionState = state;
  document.body.dataset.alpeccaVoiceSession = state;
  updateAlpeccaVoiceReadout();
}

const alpeccaVoiceSession = createHouseVoiceSessionCoordinator({
  maxQueueSize: 4,
  onStateChange: ({ current }) => setVisibleAlpeccaVoiceSession(current),
  onPlaybackStart: (moment) => alpeccaAvatarPlaybackSignal.start(moment),
  onPlaybackStop: (moment) => alpeccaAvatarPlaybackSignal.stop(moment),
  onUnavailable: ({ reason }) => {
    alpeccaAvatarPlaybackSignal.reset(reason);
    alpeccaVoiceEngine = "server voice unavailable";
    alpeccaVoiceName = "af_heart";
    alpeccaVoiceProfile = "original voice unavailable";
    alpeccaVoiceStyle = "warming";
    setAlpeccaProfileMode("listening", alpeccaActiveProfileFeature);
    updateAlpeccaVoiceReadout();
    showMessage(`Alpecca's original voice is warming or unavailable: ${reason}`, 3.4);
  },
});
let chatWasPointerLocked = false;
let alpeccaActiveSystem: AlpeccaSystemId = "overview";
let alpeccaSystemLoadSequence = 0;
let alpeccaDriveMode: DesktopPanelMode = "virtual-drive";
let alpeccaDrivePanel: DesktopPanelController | null = null;
let alpeccaDriveRequestController: AbortController | null = null;
let alpeccaVoiceLivePoll: ReturnType<typeof setInterval> | null = null;
let alpeccaServiceWorkerRegistrationPromise: Promise<ServiceWorkerRegistration | null> | null = null;
let alpeccaPushActionPending = false;
const ALPECCA_PUSH_ACK_RETRY_MESSAGE_TYPE = "alpecca:notification-ack-retry";
const ALPECCA_PUSH_ACK_RETRY_COOLDOWN_MS = 5000;
let alpeccaPushAckRetryLastRequestedAt = 0;

// Keep the Voice viewer live: while it is the open system, re-fetch /voice and
// repaint the meters in place so her modulation is seen moving, not frozen.
function stopAlpeccaVoiceLivePoll() {
  if (alpeccaVoiceLivePoll !== null) {
    clearInterval(alpeccaVoiceLivePoll);
    alpeccaVoiceLivePoll = null;
  }
}

function startAlpeccaVoiceLivePoll() {
  stopAlpeccaVoiceLivePoll();
  alpeccaVoiceLivePoll = setInterval(() => {
    if (alpeccaActiveSystem !== "voice" || alpeccaSystems.classList.contains("hidden")) {
      stopAlpeccaVoiceLivePoll();
      return;
    }
    void (async () => {
      try {
        const data = await fetchAlpeccaSystemData("voice") as Record<string, unknown>;
        if (alpeccaActiveSystem === "voice" && !alpeccaSystems.classList.contains("hidden")) {
          alpeccaSystemsBody.innerHTML = renderAlpeccaVoiceViewer(data);
        }
      } catch {
        // Transient fetch failures keep the last frame; the poll retries.
      }
    })();
  }, 1400);
}
let alpeccaScreenShareStream: MediaStream | null = null;
let alpeccaScreenShareVideo: HTMLVideoElement | null = null;
let alpeccaScreenShareTimer: number | null = null;
let alpeccaScreenShareRequest: AbortController | null = null;
let alpeccaScreenShareSequence = 0;
let alpeccaVoiceEnrollmentStream: MediaStream | null = null;
let alpeccaVoiceEnrollmentRecorder: MediaRecorder | null = null;
let alpeccaVoiceEnrollmentTimer: number | null = null;
let alpeccaVoiceEnrollmentRequest: AbortController | null = null;
let alpeccaVoiceEnrollmentSequence = 0;
let alpeccaPreloadTimer = 0;
let alpeccaExpressionProjector: AlpeccaExpressionProjector | null = null;
let alpeccaAvatarStation: AlpeccaAvatarStation | null = null;
let alpeccaDetailNoticeTimer = 0;
let alpeccaHomeNoticeTimer = 0;
const alpeccaPreloadQueue: AlpeccaAnimationName[] = [];
const alpeccaMaxConcurrentSpriteLoads = 4;
const alpeccaBackendStorageKey = "alpeccaBackendUrl";

function urlParamValue(names: string[]) {
  try {
    const params = new URL(window.location.href).searchParams;
    for (const name of names) {
      const value = params.get(name)?.trim();
      if (value) return value;
    }
  } catch {
    // Malformed launch URLs fall through to the normal local/default path.
  }
  return "";
}

function normalizeAlpeccaBackendUrl(value: string) {
  if (!value.trim()) return "";
  try {
    const url = new URL(value.trim());
    if (url.protocol !== "http:" && url.protocol !== "https:") return "";
    return url.origin;
  } catch {
    return "";
  }
}

function configuredAlpeccaBackendUrl() {
  const fromUrl = normalizeAlpeccaBackendUrl(urlParamValue(["backend", "core", "alpeccaBackend", "alpecca"]));
  if (fromUrl) {
    localStorage.setItem(alpeccaBackendStorageKey, fromUrl);
    return fromUrl;
  }
  return normalizeAlpeccaBackendUrl(localStorage.getItem(alpeccaBackendStorageKey) || "");
}

function isStaticPreviewHost(host: string) {
  return host.includes("r2.dev") || host.includes("cloudflarestorage.com") || host.includes("pages.dev");
}

const alpeccaArtBaseStorageKey = "alpeccaArtBaseUrl";
const alpeccaDefaultHfArtBaseUrl = "https://huggingface.co/datasets/CREATORJD/alpecca-runtime-assets/resolve/main/runtime-assets";

function normalizeAlpeccaArtBaseUrl(value: string) {
  if (!value.trim()) return "";
  try {
    const url = new URL(value.trim());
    if (url.protocol !== "http:" && url.protocol !== "https:") return "";
    url.search = "";
    url.hash = "";
    return url.toString().replace(/\/$/, "");
  } catch {
    return "";
  }
}

function configuredAlpeccaArtBaseUrl() {
  const fromUrl = normalizeAlpeccaArtBaseUrl(urlParamValue(["art", "artBase", "assetBase", "alpeccaArt"]));
  if (fromUrl) {
    localStorage.setItem(alpeccaArtBaseStorageKey, fromUrl);
    return fromUrl;
  }
  const stored = normalizeAlpeccaArtBaseUrl(localStorage.getItem(alpeccaArtBaseStorageKey) || "");
  if (stored) return stored;
  return isStaticPreviewHost(window.location.hostname) ? alpeccaDefaultHfArtBaseUrl : "";
}

const alpeccaArtBaseUrl = configuredAlpeccaArtBaseUrl();
const alpeccaAssetSourceManifestUrl = alpeccaAssetUrl("/assets/alpecca_asset_sources.json");
const alpeccaArtAssetMode = alpeccaArtBaseUrl ? "huggingface-runtime" : "local-fallback";
if (document.body) document.body.dataset.alpeccaArtBase = alpeccaArtBaseUrl || "local";

function alpeccaAssetUrl(path: string) {
  const cleanPath = path.replace(/^\/+/, "");
  return alpeccaArtBaseUrl ? `${alpeccaArtBaseUrl}/${cleanPath}` : `/${cleanPath}`;
}

// --- Embodiment: 2D sprite (default, always the fallback) vs experimental 3D VRM body.
const alpeccaEmbodimentStorageKey = "alpeccaEmbodiment";
type AlpeccaEmbodimentPreference = "sprite" | "vrm";
type AlpeccaEmbodimentRuntimeState = "sprite" | "loading" | "vrm" | "failed";
let alpeccaEmbodimentState: AlpeccaEmbodimentRuntimeState = "sprite";
let alpeccaVrmEmbodiment: VrmEmbodiment | null = null;
let alpeccaVrmStatusDetail = "";
let alpeccaVrmPrewarmStarted = false;

function configuredAlpeccaEmbodiment(): AlpeccaEmbodimentPreference {
  const fromUrl = urlParamValue(["embodiment", "body"]).toLowerCase();
  if (fromUrl === "vrm" || fromUrl === "3d") {
    localStorage.setItem(alpeccaEmbodimentStorageKey, "vrm");
    return "vrm";
  }
  if (fromUrl === "sprite" || fromUrl === "2d") {
    localStorage.setItem(alpeccaEmbodimentStorageKey, "sprite");
    return "sprite";
  }
  return localStorage.getItem(alpeccaEmbodimentStorageKey) === "vrm" ? "vrm" : "sprite";
}

function isAlpeccaVrm3D() {
  return alpeccaEmbodimentState === "vrm";
}

function setAlpeccaSpriteVisualsVisible(visible: boolean) {
  const layers = [
    alpecca.sprite,
    alpecca.depthProxy,
    alpecca.silhouette,
    alpecca.transitionGhost,
    alpecca.glitchRed,
    alpecca.glitchCyan,
    alpecca.glitchScanline,
    alpecca.headLook,
    alpecca.mouth,
    alpecca.heightRuler,
    alpecca.leftFootShadow,
    alpecca.rightFootShadow,
  ];
  for (const layer of layers) if (layer) layer.visible = visible;
}

function alpeccaEmotionDims() {
  return {
    love: Number(alpeccaAiState.love) || 0,
    compassion: Number(alpeccaAiState.compassion) || 0,
    fear: Number(alpeccaAiState.fear) || 0,
    energy: Number(alpeccaAiState.energy) || 0,
  };
}

function ensureAlpeccaVrmEmbodiment(): VrmEmbodiment {
  if (alpeccaVrmEmbodiment) return alpeccaVrmEmbodiment;
  alpeccaVrmEmbodiment = createVrmEmbodiment({
    parent: alpecca.group,
    targetHeight: alpeccaStandingVisibleHeight,
    groundClearance: alpeccaGroundClearance,
    manifestUrl: () => alpeccaUrlWithParams(`${alpeccaAiBaseUrl}/vrm/manifest`),
    modelUrl: (file: string, version?: string) => alpeccaUrlWithParams(
      `${alpeccaAiBaseUrl}/vrm/model/${encodeURIComponent(file)}`,
      version ? { v: version } : {},
    ),
    animationUrl: (file: string) => alpeccaUrlWithParams(`${alpeccaAiBaseUrl}/assets/vrma/${encodeURIComponent(file)}`),
    onStatus: (status, detail, progress) => {
      alpeccaVrmStatusDetail =
        status === "loading"
          ? `Loading 3D body… ${typeof progress === "number" ? `${Math.round(progress * 100)}%` : "fetching"}`
          : detail || "";
      updateCoreStatusLabels();
      if (status === "failed" && /fetch|import|network|timeout/i.test(detail || "")) {
        void recoverAlpeccaEndpoint("3d-body-load-failed", { backendStorageKey: alpeccaBackendStorageKey, force: true });
      }
    },
  });
  (window as unknown as Record<string, unknown>).__ALPECCA_VRM__ = alpeccaVrmEmbodiment;
  return alpeccaVrmEmbodiment;
}

function prewarmAlpeccaVrm() {
  if (alpeccaVrmPrewarmStarted || !alpeccaAiBaseUrl || isAlpeccaVrm3D()) return;
  alpeccaVrmPrewarmStarted = true;
  void ensureAlpeccaVrmEmbodiment().preload().then((ok) => {
    if (!ok) alpeccaVrmPrewarmStarted = false;
  });
}

async function activateAlpeccaVrm() {
  if (alpeccaEmbodimentState === "loading" || isAlpeccaVrm3D()) return;
  if (!alpeccaAiBaseUrl) {
    alpeccaVrmStatusDetail = "3D body needs a live backend URL";
    updateCoreStatusLabels();
    return;
  }
  const switchStartedAt = performance.now();
  alpeccaEmbodimentState = "loading";
  updateCoreStatusLabels();
  const ok = await ensureAlpeccaVrmEmbodiment().activate().catch(() => false);
  if (ok) {
    alpeccaEmbodimentState = "vrm";
    localStorage.setItem(alpeccaEmbodimentStorageKey, "vrm");
    setAlpeccaSpriteVisualsVisible(false);
    alpeccaVrmEmbodiment?.setMood(alpeccaAiMood, alpeccaEmotionDims());
    alpeccaVrmEmbodiment?.setSpriteState(alpecca.state, alpecca.moving, isAlpeccaTalking());
    appendAlpeccaLog("System", "Alpecca switched to her experimental 3D body.");
  } else {
    // Failure never strands her: the sprite pipeline stayed warm the whole time.
    alpeccaEmbodimentState = "failed";
    localStorage.setItem(alpeccaEmbodimentStorageKey, "sprite");
    setAlpeccaSpriteVisualsVisible(true);
    if (!alpeccaVrmStatusDetail) alpeccaVrmStatusDetail = "3D body failed to load; staying 2D";
  }
  document.body.dataset.alpeccaVrmSwitchMs = Math.round(performance.now() - switchStartedAt).toString();
  updateCoreStatusLabels();
}

function deactivateAlpeccaVrm() {
  releaseAlpeccaVrmTerminalTarget();
  alpeccaVrmEmbodiment?.deactivate();
  if (window.__HOUSE_DEBUG__?.alpecca) delete window.__HOUSE_DEBUG__.alpecca.vrm;
  delete document.body.dataset.alpeccaVrmFeet;
  alpeccaEmbodimentState = "sprite";
  localStorage.setItem(alpeccaEmbodimentStorageKey, "sprite");
  setAlpeccaSpriteVisualsVisible(true);
  alpeccaVrmStatusDetail = "";
  updateCoreStatusLabels();
}

function updateAlpeccaEmbodiment(dt: number) {
  if (!isAlpeccaVrm3D() || !alpeccaVrmEmbodiment) return;
  const talking = isAlpeccaTalking();
  const engaged = talking || alpecca.attentionTimer > 0 || !alpeccaChat.classList.contains("hidden");
  const presentationCamera = alpeccaPresentationCamera();
  const distanceToPlayer = Math.hypot(
    presentationCamera.position.x - alpecca.group.position.x,
    presentationCamera.position.z - alpecca.group.position.z,
  );
  alpeccaVrmEmbodiment.setSpriteState(
    alpecca.state,
    alpecca.moving,
    talking,
    false,
    alpecca.walkSpeed,
    alpeccaLastMove,
  );
  alpeccaVrmEmbodiment.update(dt, presentationCamera, engaged, distanceToPlayer);
  const vrmDebug = alpeccaVrmEmbodiment.debug();
  document.body.dataset.alpeccaVrmFeet = JSON.stringify(vrmDebug.feet);
  if (window.__HOUSE_DEBUG__?.alpecca) {
    window.__HOUSE_DEBUG__.alpecca.vrm = vrmDebug;
  }
}

// --- HUD density: minimal chip HUD vs the full card stack.
function resolvedHudMode(): "minimal" | "full" {
  if (alpeccaAppMemory.hudMode === "minimal") return "minimal";
  if (alpeccaAppMemory.hudMode === "full") return "full";
  return window.innerWidth <= 900 || window.matchMedia("(pointer: coarse)").matches ? "minimal" : "full";
}

function applyHudMode() {
  const minimal = resolvedHudMode() === "minimal";
  document.body.classList.toggle("hud-minimal", minimal);
  if (!minimal) collapseHudCards();
}

const hudExpandableCards: Record<string, () => HTMLElement> = {
  topbar: () => topbarEl,
  roomPanel: () => roomPanel,
  livingState: () => alpeccaLivingStateEl,
  sourcePanel: () => alpeccaSourcePanel,
};
let hudExpandedCard = "";
let hudExpandCollapseTimer: ReturnType<typeof setTimeout> | null = null;

function collapseHudCards() {
  hudExpandedCard = "";
  if (hudExpandCollapseTimer) {
    clearTimeout(hudExpandCollapseTimer);
    hudExpandCollapseTimer = null;
  }
  for (const getter of Object.values(hudExpandableCards)) getter().classList.remove("hud-expanded");
  for (const chip of [chipMission, chipRoom, chipLoop, sourceChip]) chip.setAttribute("aria-expanded", "false");
}

function toggleHudCard(target: string, chip: HTMLButtonElement) {
  const wasOpen = hudExpandedCard === target;
  collapseHudCards();
  if (wasOpen) return;
  const card = hudExpandableCards[target]?.();
  if (!card) return;
  hudExpandedCard = target;
  card.classList.add("hud-expanded");
  chip.setAttribute("aria-expanded", "true");
  hudExpandCollapseTimer = setTimeout(collapseHudCards, 8000);
}

function defaultAlpeccaHttpBaseUrl() {
  const configured = configuredAlpeccaBackendUrl();
  if (configured) return configured;
  const host = window.location.hostname;
  const localVite = (host === "127.0.0.1" || host === "localhost") && window.location.port === "5173";
  if (isStaticPreviewHost(host)) return "";
  return localVite ? "http://127.0.0.1:8765" : window.location.origin;
}

function defaultAlpeccaWsBaseUrl() {
  const configured = configuredAlpeccaBackendUrl();
  if (configured) {
    const url = new URL(configured);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    url.pathname = "/ws/house-hq";
    url.search = "";
    url.hash = "";
    return url.toString();
  }
  const host = window.location.hostname;
  const localVite = (host === "127.0.0.1" || host === "localhost") && window.location.port === "5173";
  if (isStaticPreviewHost(host)) return "";
  if (localVite) return "ws://127.0.0.1:8765/ws/house-hq";
  const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${window.location.host}/ws/house-hq`;
}

const alpeccaAiBaseUrl = defaultAlpeccaHttpBaseUrl();
const alpeccaAiWsBaseUrl = defaultAlpeccaWsBaseUrl();
alpeccaBackendInput.value = alpeccaAiBaseUrl;
const alpeccaSourceArtRoot = alpeccaAssetUrl("/assets/alpecca-source");
const alpeccaExpressionRoot = alpeccaAssetUrl("/assets/alpecca-expressions");
const alpeccaAvatarRoot = alpeccaAssetUrl("/assets/alpecca-avatar");
const alpeccaChatExpressionRoot = alpeccaAssetUrl("/assets/alpecca-chat");
const alpeccaAppMemoryStorageKey = "alpeccaAppMemory";
const alpeccaAppMemory = loadAlpeccaAppMemory();
const alpeccaAvatarAssets: AlpeccaAvatarAsset[] = [
  { id: "source", label: "Avatar Source", file: "source" },
  { id: "portrait_idle", label: "Portrait Idle", file: "portraits/idle" },
  { id: "portrait_speaking", label: "Portrait Speaking", file: "portraits/speaking" },
  { id: "portrait_thinking", label: "Portrait Thinking", file: "portraits/thinking" },
  { id: "pose_lean", label: "Pose Lean", file: "poses/lean" },
  { id: "pose_present", label: "Pose Present", file: "poses/present" },
  { id: "pose_reach", label: "Pose Reach", file: "poses/reach" },
  { id: "pose_rest", label: "Pose Rest", file: "poses/rest" },
  { id: "pose_shy", label: "Pose Shy", file: "poses/shy" },
  { id: "pose_walk", label: "Pose Walk", file: "poses/walk" },
  { id: "talkinghead_her", label: "Talking Head", file: "talkinghead/her" },
];
let alpeccaAvatarCycleIndex = 0;
let alpeccaAvatarManualTimer = 0;
let alpeccaChatExpressionAtlas: AlpeccaChatExpressionAtlas | null = null;
let alpeccaChatExpressionFrameIndex = -1;
let alpeccaChatExpressionLabel = "";
let alpeccaProfileMouthMode = "fallback-overlay";
let alpeccaProfileTalkFrame = "";
let alpeccaProfileTalkFrameKey = "";
let alpeccaProfileTalkFrameTier = -1;
let alpeccaProfileLastTalkFrameAt = 0;
let alpeccaProfileHeldExpression: AlpeccaChatExpressionFrame | undefined;
let alpeccaProfileMode = "listening";
let alpeccaActiveProfileFeature = "";
let alpeccaProfileGlitchTimer = 0;
let alpeccaPerceptionTimer = 2.8;
let alpeccaPerceptionSendTimer = 0;
let alpeccaPresenceContextTimer = 1.2;
let alpeccaLastPresenceContextKey = "";
let alpeccaLastSeenLabel = "";
let alpeccaLastQuestion = "";
let alpeccaCreatedObjectId = 0;
const alpeccaExpressionIds = [
  "neutral",
  "warm_smile",
  "happy",
  "playful",
  "curious",
  "thinking",
  "compassionate",
  "reassuring",
  "gentle",
  "protective",
  "concerned",
  "fear_spike",
  "soft_sadness",
  "low_power",
  "apologetic",
  "overload",
];
let alpeccaExpressionCycleIndex = 0;
let alpeccaExpressionManualTimer = 0;
let alpeccaAgiLayerIndex = 0;
let alpeccaAgiAutonomyTimer = 10;
let alpeccaAgiNoticeTimer = 0;
let alpeccaCuriosityTimer = 18;
let alpeccaCuriosityNoticeTimer = 0;
let alpeccaWorldTickTimer = 42;
let alpeccaWorldTickInFlight = false;
let alpeccaAutonomyPollTimer = 4;
let alpeccaAutonomyPollInFlight = false;
let alpeccaLastAutonomyKey = "";
let alpeccaAgiJournal: AlpeccaAgiJournal | null = null;
let alpeccaImprovementQueue: AlpeccaImprovementQueue | null = null;
const alpeccaSourcePlates: Record<string, AlpeccaSourcePlate> = {
  movement: {
    id: "movement",
    label: "Movement Library",
    hint: "Directional walk/run reference from Alpecca source data",
    file: "movement",
  },
  gestures: {
    id: "gestures",
    label: "Gesture UI",
    hint: "Talk, point, pickup, and hand-state reference",
    file: "gestures",
  },
  expressions: {
    id: "expressions",
    label: "Expression + Phoneme Sheet",
    hint: "Mood and reply expression reference",
    file: "expressions",
  },
  wardrobe: {
    id: "wardrobe",
    label: "Wardrobe Modes",
    hint: "Identity and mode styling reference",
    file: "wardrobe",
  },
  master: {
    id: "master",
    label: "Master Character Sheet",
    hint: "Canonical Alpecca design reference",
    file: "master",
  },
};
let currentAlpeccaSourcePlate = "";
setAlpeccaSourcePlate("master");
const alpeccaSourceFeatures: Record<string, AlpeccaSourceFeature> = {
  self: {
    id: "self",
    label: "Ask self-report",
    room: "Self Design",
    prompt: "Give me a short grounded self-report from your current Alpecca internals: mood, why it moved, and what you want next.",
    page: "/introspect",
    toolPath: "/introspect",
    color: "#d86a8d",
  },
  memory: {
    id: "memory",
    label: "Ask memory scan",
    room: "Library",
    prompt: "Briefly summarize what you remember that matters most for this AI Office HQ project right now.",
    page: "/memories",
    toolPath: "/memories/search",
    color: "#f0bd59",
  },
  journal: {
    id: "journal",
    label: "Ask journal reflection",
    room: "Library",
    prompt: "Write a short project journal reflection about this house becoming your office HQ.",
    page: "/journal",
    toolPath: "/journal",
    color: "#b9d7dc",
  },
  studio: {
    id: "studio",
    label: "Ask studio direction",
    room: "Workshop",
    prompt: "From your design studio perspective, suggest one visual or avatar improvement for this house game.",
    page: "/studio",
    toolPath: "/growth",
    color: "#9f8cff",
  },
  home: {
    id: "home",
    label: "Ask home state",
    room: "HQ Control",
    prompt: "Report your current home state and which room is calling you, in one concise in-world update.",
    page: "/home",
    toolPath: "/home/state",
    color: "#4be4ff",
  },
  soul: {
    id: "soul",
    label: "Ask soul charter",
    room: "Observatory",
    prompt: "Explain your current values or charter constraints in one short, grounded game-facing update.",
    page: "/soul",
    toolPath: "/soul",
    color: "#8eeeff",
  },
};

const hqOfficeRooms: OfficeRoom[] = [
  {
    id: "hq-control",
    name: "HQ Control",
    stationId: "hq-control",
    purpose: "Command room for project routing, status, and live coordination.",
    system: "Control console",
    bounds: { minX: -7.6, maxX: -1.55, minZ: 1.35, maxZ: 5.65 },
  },
  {
    id: "library",
    name: "Library",
    stationId: "library",
    purpose: "Memory, research, references, and context recovery.",
    system: "Catalog sync",
    bounds: { minX: -7.6, maxX: -1.55, minZ: -5.65, maxZ: -1.08 },
  },
  {
    id: "self-design",
    name: "Self Design",
    stationId: "self-design",
    purpose: "Identity, avatar design, reflection, and self-model checks.",
    system: "Design console",
    bounds: { minX: -7.6, maxX: -1.55, minZ: -1.08, maxZ: 1.35 },
  },
  {
    id: "observatory",
    name: "AI Observatory",
    stationId: "observatory",
    purpose: "Creative review, media streams, and watchful analysis.",
    system: "Media deck",
    bounds: { minX: 2.05, maxX: 7.6, minZ: -1.08, maxZ: 5.65 },
  },
  {
    id: "workshop",
    name: "Workshop",
    stationId: "workshop",
    purpose: "Prototype bench for tools, experiments, and build tests.",
    system: "Prototype bench",
    bounds: { minX: 2.05, maxX: 7.6, minZ: -5.65, maxZ: -1.08 },
  },
];

const hqEntryRoom: OfficeRoom = {
  id: "entry",
  name: "Entry Hall",
  stationId: "entry",
  purpose: "Central walkway connecting the five office rooms.",
  system: "Navigation spine",
  bounds: { minX: -1.55, maxX: 2.05, minZ: -5.65, maxZ: 5.65 },
};

function stageRect(label: string, center: THREE.Vector3Tuple, size: THREE.Vector2Tuple, color: string): RoomStageRect {
  return {
    label,
    center: new THREE.Vector3(center[0], center[1], center[2]),
    size: new THREE.Vector2(size[0], size[1]),
    color,
  };
}

const alpeccaStageSpecs: RoomStageSpec[] = [
  {
    roomId: "hq-control",
    walkable: stageRect("HQ walkable floor", [-4.58, 0.062, 3.42], [4.55, 3.8], "#8eeeff"),
    safeLane: stageRect("HQ clear lane", [-3.52, 0.066, 3.56], [2.05, 2.25], "#ffffff"),
    stagePad: stageRect("HQ command stage", [-3.48, 0.071, 2.72], [1.85, 1.85], "#8eeeff"),
    inspectPad: stageRect("Control console approach", [-4.45, 0.073, 2.55], [1.45, 1.45], "#f0bd59"),
    chatPad: stageRect("HQ player view pad", [-2.68, 0.074, 3.62], [1.85, 1.65], "#d86a8d"),
    restPad: stageRect("Recovery rest pose pad", [-5.74, 0.075, 3.72], [1.95, 1.45], "#9f8cff"),
    portals: [{ id: "hq-entry-frame", to: "entry", center: new THREE.Vector3(-1.28, 0.04, 4.38), width: 1.8 }],
    terminals: ["hq-control", "home", "alpecca-rest-nook"],
    occlusionPlanes: [
      stageRect("HQ console depth plane", [-4.45, 0.08, 2.55], [1.6, 0.24], "#8eeeff"),
      stageRect("Rest nook depth plane", [-5.98, 0.08, 4.28], [2.2, 0.24], "#9f8cff"),
    ],
  },
  {
    roomId: "library",
    walkable: stageRect("Library walkable floor", [-4.88, 0.062, -3.35], [4.95, 3.92], "#8eeeff"),
    safeLane: stageRect("Library clear lane", [-3.72, 0.066, -2.64], [2.45, 2.1], "#ffffff"),
    stagePad: stageRect("Library memory stage", [-5.15, 0.071, -2.82], [1.85, 1.85], "#8eeeff"),
    inspectPad: stageRect("Catalog approach", [-6.25, 0.073, -2.55], [1.45, 1.45], "#f0bd59"),
    chatPad: stageRect("Library player view pad", [-3.12, 0.074, -2.08], [1.8, 1.55], "#d86a8d"),
    portals: [{ id: "library-entry-frame", to: "entry", center: new THREE.Vector3(-1.28, 0.04, -0.96), width: 1.8 }],
    terminals: ["library", "memory", "archive-cabinet"],
    occlusionPlanes: [stageRect("Bookshelf depth plane", [-7.22, 0.08, -3.34], [0.24, 2.7], "#8eeeff")],
  },
  {
    roomId: "self-design",
    walkable: stageRect("Self Design walkable floor", [-5.18, 0.062, 0.55], [4.55, 1.92], "#8eeeff"),
    safeLane: stageRect("Self Design clear lane", [-4.22, 0.066, 0.58], [2.15, 1.48], "#ffffff"),
    stagePad: stageRect("Self Design avatar stage", [-5.05, 0.071, 0.62], [1.8, 1.52], "#8eeeff"),
    inspectPad: stageRect("Mirror approach", [-6.24, 0.073, 0.72], [1.38, 1.28], "#f0bd59"),
    chatPad: stageRect("Self Design player view pad", [-3.12, 0.074, 0.62], [1.75, 1.35], "#d86a8d"),
    portals: [{ id: "self-entry-frame", to: "entry", center: new THREE.Vector3(-1.28, 0.04, 0.52), width: 1.8 }],
    terminals: ["self-design", "self", "drawer"],
    occlusionPlanes: [stageRect("Mirror depth plane", [-7.38, 0.08, 0.65], [0.24, 1.65], "#8eeeff")],
  },
  {
    roomId: "observatory",
    walkable: stageRect("Observatory walkable floor", [4.92, 0.062, 3.12], [4.65, 4.78], "#8eeeff"),
    safeLane: stageRect("Observatory clear lane", [3.72, 0.066, 3.28], [2.25, 2.55], "#ffffff"),
    stagePad: stageRect("Observatory watching stage", [4.2, 0.071, 2.78], [1.9, 1.9], "#8eeeff"),
    inspectPad: stageRect("Media deck approach", [5.0, 0.073, 2.55], [1.5, 1.5], "#f0bd59"),
    chatPad: stageRect("Observatory player view pad", [3.05, 0.074, 3.86], [1.85, 1.65], "#d86a8d"),
    portals: [{ id: "observatory-entry-frame", to: "entry", center: new THREE.Vector3(1.8, 0.04, 4.18), width: 1.8 }],
    terminals: ["observatory", "soul", "observatory-rack"],
    occlusionPlanes: [stageRect("Media counter depth plane", [5.0, 0.08, 5.02], [3.8, 0.24], "#8eeeff")],
  },
  {
    roomId: "workshop",
    walkable: stageRect("Workshop walkable floor", [5.32, 0.062, -3.52], [4.62, 3.75], "#8eeeff"),
    safeLane: stageRect("Workshop clear lane", [4.3, 0.066, -3.48], [2.18, 2.18], "#ffffff"),
    stagePad: stageRect("Workshop prototype stage", [4.18, 0.071, -3.48], [1.9, 1.9], "#8eeeff"),
    inspectPad: stageRect("Prototype bench approach", [5.2, 0.073, -4.28], [1.5, 1.5], "#f0bd59"),
    chatPad: stageRect("Workshop player view pad", [3.0, 0.074, -2.18], [1.75, 1.55], "#d86a8d"),
    portals: [{ id: "workshop-entry-frame", to: "entry", center: new THREE.Vector3(1.8, 0.04, -1.45), width: 1.8 }],
    terminals: ["workshop", "studio", "prototype-rinse-tray"],
    occlusionPlanes: [stageRect("Workbench depth plane", [5.2, 0.08, -4.58], [2.45, 0.24], "#8eeeff")],
  },
  {
    roomId: "entry",
    walkable: stageRect("Entry walkable spine", [0.2, 0.062, -0.25], [2.15, 10.15], "#8eeeff"),
    safeLane: stageRect("Entry two-character lane", [0.2, 0.066, -0.25], [1.88, 9.35], "#ffffff"),
    stagePad: stageRect("Entry orientation stage", [0.15, 0.071, -0.15], [1.8, 1.8], "#8eeeff"),
    inspectPad: stageRect("Entry route decision pad", [0.15, 0.073, -0.15], [1.6, 1.6], "#f0bd59"),
    chatPad: stageRect("Entry player view pad", [0.15, 0.074, 1.48], [1.85, 1.55], "#d86a8d"),
    portals: [
      { id: "entry-hq-frame", to: "hq-control", center: new THREE.Vector3(-1.28, 0.04, 4.38), width: 1.8 },
      { id: "entry-library-frame", to: "library", center: new THREE.Vector3(-1.28, 0.04, -0.96), width: 1.8 },
      { id: "entry-self-frame", to: "self-design", center: new THREE.Vector3(-1.28, 0.04, 0.52), width: 1.8 },
      { id: "entry-observatory-frame", to: "observatory", center: new THREE.Vector3(1.8, 0.04, 4.18), width: 1.8 },
      { id: "entry-workshop-frame", to: "workshop", center: new THREE.Vector3(1.8, 0.04, -1.45), width: 1.8 },
    ],
    terminals: ["front door"],
    occlusionPlanes: [],
  },
];
const alpeccaStageSpecsByRoom = new Map(alpeccaStageSpecs.map((spec) => [spec.roomId, spec]));
let alpeccaStageQaGroup: THREE.Group | null = null;
let alpeccaStageQaIssues: string[] = [];
let alpeccaCylinderQaManualVisible: boolean | null = null;
let alpeccaLastViewMatrix: AlpeccaViewMatrixState = {
  vertical: "eye",
  horizontal: "front",
  flipX: false,
  relativeYawDeg: 0,
  cameraPitchDeg: 0,
  sector16: 0,
  sector16Key: "s00",
  cylinderRadius: alpeccaCylinderFarRadius,
  cylinderZone: "far-shell",
  cylinderPlayerDistance: 0,
  volumeZone: "far",
  volumeProbe: "torso",
  volumeDepth: 0,
  sampleY: 0.96,
  billboardClampDeg: 24,
  key: "eye_front",
};

function alpeccaStageSpecForRoom(roomId: string) {
  return alpeccaStageSpecsByRoom.get(roomId) ?? alpeccaStageSpecsByRoom.get("entry")!;
}

function alpeccaStageSpecForPosition(x: number, z: number) {
  return alpeccaStageSpecForRoom(officeRoomAtPosition(x, z).id);
}

function alpeccaStageRectContains(rect: RoomStageRect, x: number, z: number, margin = 0) {
  return (
    x >= rect.center.x - rect.size.x / 2 - margin &&
    x <= rect.center.x + rect.size.x / 2 + margin &&
    z >= rect.center.z - rect.size.y / 2 - margin &&
    z <= rect.center.z + rect.size.y / 2 + margin
  );
}

function alpeccaStagePadLabelForPosition(x: number, z: number) {
  const spec = alpeccaStageSpecForPosition(x, z);
  const pads = [spec.stagePad, spec.inspectPad, spec.chatPad, spec.restPad].filter(Boolean) as RoomStageRect[];
  const pad = pads.find((item) => alpeccaStageRectContains(item, x, z, 0.08));
  return pad?.label ?? spec.walkable.label;
}

function nearestWallClearance(x: number, z: number) {
  let nearest = Infinity;
  for (const wall of walls) {
    const nearestX = THREE.MathUtils.clamp(x, wall.minX, wall.maxX);
    const nearestZ = THREE.MathUtils.clamp(z, wall.minZ, wall.maxZ);
    nearest = Math.min(nearest, Math.hypot(x - nearestX, z - nearestZ));
  }
  return Number.isFinite(nearest) ? nearest : 9;
}

function alpeccaNavClearanceLabel() {
  const spec = alpeccaStageSpecForPosition(alpecca.group.position.x, alpecca.group.position.z);
  const insideWalkable = alpeccaStageRectContains(spec.walkable, alpecca.group.position.x, alpecca.group.position.z, 0.05);
  const clearance = nearestWallClearance(alpecca.group.position.x, alpecca.group.position.z);
  const stage = insideWalkable ? "walkable" : "outside-walkable";
  return `${stage}:${clearance.toFixed(2)}m`;
}

function normalizeAngleDeg(value: number) {
  return THREE.MathUtils.euclideanModulo(value + 180, 360) - 180;
}

function alpeccaHorizontalTierForYaw(absYaw: number, previous: AlpeccaViewHorizontalTier): AlpeccaViewHorizontalTier {
  const hysteresis = 10;
  if (previous === "front" && absYaw < 22.5 + hysteresis) return "front";
  if (previous === "frontDiag" && absYaw > 22.5 - hysteresis && absYaw < 67.5 + hysteresis) return "frontDiag";
  if (previous === "side" && absYaw > 67.5 - hysteresis && absYaw < 112.5 + hysteresis) return "side";
  if (previous === "backDiag" && absYaw > 112.5 - hysteresis && absYaw < 157.5 + hysteresis) return "backDiag";
  if (previous === "back" && absYaw > 157.5 - hysteresis) return "back";
  return absYaw < 22.5 ? "front" : absYaw < 67.5 ? "frontDiag" : absYaw < 112.5 ? "side" : absYaw < 157.5 ? "backDiag" : "back";
}

function alpeccaSector16ForYaw(relativeYawDeg: number) {
  const sector = Math.floor(((relativeYawDeg + 11.25 + 360) % 360) / 22.5) % 16;
  return sector;
}

function alpeccaSector16Key(sector: number): AlpeccaViewSector16Key {
  return `s${String(THREE.MathUtils.euclideanModulo(Math.round(sector), 16)).padStart(2, "0")}` as AlpeccaViewSector16Key;
}

function alpeccaSector16RuntimeKey(sector: number) {
  return `s${THREE.MathUtils.euclideanModulo(Math.round(sector), 16)}`;
}

function alpeccaCylinderZoneForDistance(distance: number) {
  if (distance <= alpeccaCylinderBodyRadius) return "near-body";
  if (distance <= alpeccaCylinderInteractionRadius) return "interaction-shell";
  return "far-shell";
}

function alpeccaVerticalTierForView(cameraPitchDeg: number, torsoDelta: number, previous: AlpeccaViewVerticalTier): AlpeccaViewVerticalTier {
  if (previous === "low" && (torsoDelta < -0.08 || cameraPitchDeg > 9)) return "low";
  if (previous === "high" && (torsoDelta > 0.08 || cameraPitchDeg < -10)) return "high";
  if (cameraPitchDeg > 18 || torsoDelta < -0.22) return "low";
  if (cameraPitchDeg < -20 || torsoDelta > 0.24) return "high";
  return "eye";
}

function computeAlpeccaViewMatrix(): AlpeccaViewMatrixState {
  const viewCamera = alpeccaPresentationCamera();
  const bodyBaseY = alpecca.group.position.y;
  const footY = bodyBaseY + 0.1;
  const torsoY = bodyBaseY + 0.94;
  const headY = bodyBaseY + 1.52;
  const viewHeight = viewCamera.position.y - bodyBaseY;
  const volumeProbe = viewHeight > 1.28 ? "head" : viewHeight < 0.52 ? "feet" : "torso";
  const sampleY = volumeProbe === "head" ? headY : volumeProbe === "feet" ? footY : torsoY;
  const toCameraX = viewCamera.position.x - alpecca.group.position.x;
  const toCameraZ = viewCamera.position.z - alpecca.group.position.z;
  const horizontalDistance = Math.max(0.001, Math.hypot(toCameraX, toCameraZ));
  const bodyYaw = alpecca.groundYaw || alpecca.group.rotation.y;
  const forwardX = Math.sin(bodyYaw);
  const forwardZ = Math.cos(bodyYaw);
  const rightX = Math.cos(bodyYaw);
  const rightZ = -Math.sin(bodyYaw);
  const localForward = toCameraX * forwardX + toCameraZ * forwardZ;
  const localRight = toCameraX * rightX + toCameraZ * rightZ;
  const relativeYawRad = Math.atan2(localRight, localForward);
  const relativeYawDeg = normalizeAngleDeg(THREE.MathUtils.radToDeg(relativeYawRad));
  const sector16 = alpeccaSector16ForYaw(relativeYawDeg);
  const sector16Key = alpeccaSector16Key(sector16);
  const absYaw = Math.abs(relativeYawDeg);
  const horizontal = alpeccaHorizontalTierForYaw(absYaw, alpeccaLastViewMatrix.horizontal);
  const cameraPitchDeg = THREE.MathUtils.radToDeg(Math.atan2(sampleY - viewCamera.position.y, horizontalDistance));
  const verticalDistance = (viewCamera.position.y - torsoY) / Math.max(0.1, alpeccaStandingVisibleHeight * 0.5);
  const volumeDepth = Math.sqrt(
    (localRight / 0.68) ** 2 +
      (localForward / 0.82) ** 2 +
      verticalDistance ** 2,
  );
  const cylinderZone = alpeccaCylinderZoneForDistance(horizontalDistance);
  const cylinderRadius =
    cylinderZone === "near-body"
      ? alpeccaCylinderBodyRadius
      : cylinderZone === "interaction-shell"
        ? alpeccaCylinderInteractionRadius
        : alpeccaCylinderFarRadius;
  const volumeZone = cylinderZone;
  const vertical = alpeccaVerticalTierForView(cameraPitchDeg, viewCamera.position.y - torsoY, alpeccaLastViewMatrix.vertical);
  const flipX = relativeYawDeg < -22.5 && relativeYawDeg > -157.5;
  const sectorCenterDeg = normalizeAngleDeg(sector16 * 22.5);
  const sectorDeltaDeg = Math.abs(normalizeAngleDeg(relativeYawDeg - sectorCenterDeg));
  const billboardClampDeg = Math.max(4, Math.min(18, sectorDeltaDeg + (volumeZone === "near-body" ? 2 : volumeZone === "interaction-shell" ? 4 : 6)));
  return {
    vertical,
    horizontal,
    flipX,
    relativeYawDeg: Number(relativeYawDeg.toFixed(1)),
    cameraPitchDeg: Number(cameraPitchDeg.toFixed(1)),
    sector16,
    sector16Key,
    cylinderRadius,
    cylinderZone,
    cylinderPlayerDistance: Number(horizontalDistance.toFixed(2)),
    volumeZone,
    volumeProbe,
    volumeDepth: Number(volumeDepth.toFixed(2)),
    sampleY: Number((sampleY - bodyBaseY).toFixed(2)),
    billboardClampDeg,
    key: `${vertical}_${horizontal}`,
  };
}

function routeSegmentIntersectsWall(from: THREE.Vector3, to: THREE.Vector3, radius = 0.3) {
  const distance = Math.max(0.001, from.distanceTo(to));
  const steps = Math.max(8, Math.ceil(distance * 8));
  for (let i = 1; i < steps; i += 1) {
    const t = i / steps;
    const x = THREE.MathUtils.lerp(from.x, to.x, t);
    const z = THREE.MathUtils.lerp(from.z, to.z, t);
    if (alpeccaCollides(x, z)) return true;
    if (nearestWallClearance(x, z) < radius * 0.72) return true;
  }
  return false;
}

function validateAlpeccaAccommodation() {
  const issues: string[] = [];
  for (const spec of alpeccaStageSpecs) {
    if (spec.safeLane.size.x < 1.8 && spec.safeLane.size.y < 1.8) issues.push(`${spec.roomId}: safe lane under 1.8m`);
    if (spec.stagePad.size.x < 1.8 || spec.stagePad.size.y < 1.35) issues.push(`${spec.roomId}: stage pad too small`);
    if (spec.chatPad.size.x < 1.65 || spec.chatPad.size.y < 1.35) issues.push(`${spec.roomId}: chat pad too small`);
    for (const portal of spec.portals) {
      if (portal.width < 1.6) issues.push(`${spec.roomId}: ${portal.id} below 1.6m opening`);
    }
  }
  for (const point of alpeccaExplorePoints) {
    const spec = alpeccaStageSpecForRoom(point.roomId);
    if (!alpeccaStageRectContains(spec.walkable, point.position.x, point.position.z, 0.18)) issues.push(`${point.roomName}: explore point outside walkable stage`);
  }
  for (let index = 0; index < alpeccaExplorePoints.length; index += 1) {
    const route = buildAlpeccaRoute(index);
    for (let step = 1; step < route.length; step += 1) {
      if (routeSegmentIntersectsWall(route[step - 1], route[step])) {
        issues.push(`${alpeccaExplorePoints[index].roomName}: route segment ${step} needs clearance`);
        break;
      }
    }
  }
  alpeccaStageQaIssues = issues.slice(0, 8);
  return alpeccaStageQaIssues;
}

const hqAlpeccaExplorePoints: AlpeccaExplorePoint[] = [
  {
    roomId: "hq-control",
    roomName: "HQ Control",
    label: "checking the control console",
    position: new THREE.Vector3(-3.48, 0.04, 2.72),
    lookAt: new THREE.Vector3(-4.45, 0.98, 2.55),
    animation: "point",
    freedomAnimations: ["point", "pickup", "crouch"],
    featureId: "home",
    action: "routes project status through the HQ console",
  },
  {
    roomId: "hq-control",
    roomName: "HQ Rest Nook",
    label: "resting on the recovery sofa",
    position: new THREE.Vector3(-5.74, 0.04, 3.72),
    lookAt: new THREE.Vector3(-6.05, 0.62, 4.62),
    animation: "sleepSoutheast",
    freedomAnimations: ["sleepSoutheast"],
    restOnly: true,
    action: "rests in her recovery nook until she is ready to re-engage",
  },
  {
    roomId: "library",
    roomName: "Library",
    label: "reviewing memory shelves",
    position: new THREE.Vector3(-5.15, 0.04, -2.82),
    lookAt: new THREE.Vector3(-6.25, 1.0, -2.55),
    animation: "point",
    freedomAnimations: ["point", "pickup", "kneel"],
    featureId: "memory",
    action: "cross-checks memory shelves against live context",
  },
  {
    roomId: "self-design",
    roomName: "Self Design",
    label: "checking the avatar mirror",
    position: new THREE.Vector3(-5.05, 0.04, 0.62),
    lookAt: new THREE.Vector3(-7.42, 1.2, 0.65),
    animation: "kneel",
    freedomAnimations: ["kneel", "point", "crouch"],
    featureId: "self",
    action: "compares her current mood against the avatar mirror",
  },
  {
    roomId: "observatory",
    roomName: "AI Observatory",
    label: "watching the media deck",
    position: new THREE.Vector3(4.2, 0.04, 2.78),
    lookAt: new THREE.Vector3(5.0, 0.98, 2.55),
    animation: "point",
    freedomAnimations: ["point", "kneel", "idleNortheast"],
    featureId: "soul",
    action: "reviews creative signals on the observatory deck",
  },
  {
    roomId: "workshop",
    roomName: "Workshop",
    label: "inspecting prototype tools",
    position: new THREE.Vector3(4.18, 0.04, -3.48),
    lookAt: new THREE.Vector3(5.2, 0.95, -4.78),
    animation: "pickup",
    freedomAnimations: ["pickup", "crouch", "point", "kneel"],
    featureId: "studio",
    action: "tests prototype ideas at the workshop bench",
  },
  {
    roomId: "entry",
    roomName: "Entry Hall",
    label: "routing between rooms",
    position: new THREE.Vector3(0.15, 0.04, -0.15),
    lookAt: new THREE.Vector3(0, 1.2, 0.8),
    animation: "idle",
    freedomAnimations: ["idleDown", "point"],
    action: "listens between rooms and chooses a new path",
  },
];

const hqAlpeccaRouteGuides: Record<string, AlpeccaRouteGuide> = {
  "hq-control": {
    hall: new THREE.Vector3(-0.78, 0.04, 4.4),
    door: new THREE.Vector3(-1.22, 0.04, 4.38),
    approach: new THREE.Vector3(-2.05, 0.04, 4.32),
  },
  library: {
    hall: new THREE.Vector3(-0.82, 0.04, -0.92),
    door: new THREE.Vector3(-1.24, 0.04, -0.96),
    approach: new THREE.Vector3(-2.12, 0.04, -1.02),
  },
  "self-design": {
    hall: new THREE.Vector3(-0.82, 0.04, 0.42),
    door: new THREE.Vector3(-1.22, 0.04, 0.52),
    approach: new THREE.Vector3(-2.35, 0.04, 0.68),
  },
  observatory: {
    hall: new THREE.Vector3(1.24, 0.04, 4.18),
    door: new THREE.Vector3(1.78, 0.04, 4.18),
    approach: new THREE.Vector3(2.55, 0.04, 4.18),
  },
  workshop: {
    hall: new THREE.Vector3(1.24, 0.04, -1.42),
    door: new THREE.Vector3(1.78, 0.04, -1.45),
    approach: new THREE.Vector3(2.55, 0.04, -1.82),
  },
  entry: {
    hall: new THREE.Vector3(0.15, 0.04, -0.15),
    door: new THREE.Vector3(0.15, 0.04, -0.15),
    approach: new THREE.Vector3(0.15, 0.04, -0.15),
  },
};

const prototypeRooms: OfficeRoom[] = [
  {
    id: "void-core",
    name: "Void Core",
    stationId: "void-core",
    purpose: "Minimal training stage for Alpecca movement, voice, perception, and self-tests.",
    system: "Core monitor",
    bounds: { minX: -2.1, maxX: 2.1, minZ: -2.25, maxZ: 1.55 },
  },
  {
    id: "terminal-ring",
    name: "Terminal Ring",
    stationId: "terminal-ring",
    purpose: "Floating terminals for memory, source, voice, and animation tests.",
    system: "Terminal array",
    bounds: { minX: -4.8, maxX: 4.8, minZ: -4.75, maxZ: 4.25 },
  },
  {
    id: "creator-light",
    name: "Creator Light",
    stationId: "creator-light",
    purpose: "Player focus area where Alpecca can see, approach, and respond cleanly.",
    system: "Projector focus",
    bounds: { minX: -1.5, maxX: 1.5, minZ: 1.55, maxZ: 4.85 },
  },
];

const prototypeEntryRoom: OfficeRoom = {
  id: "entry",
  name: "Prototype Void",
  stationId: "entry",
  purpose: "Open dark testing space for Alpecca's embodied behavior.",
  system: "Void shell",
  bounds: { minX: -5.25, maxX: 5.25, minZ: -5.25, maxZ: 5.25 },
};

const prototypeAlpeccaExplorePoints: AlpeccaExplorePoint[] = [
  {
    roomId: "void-core",
    roomName: "Void Core",
    label: "checking the floating monitor",
    position: new THREE.Vector3(-0.9, 0.04, -1.25),
    lookAt: new THREE.Vector3(0, 1.38, -2.45),
    animation: "point",
    freedomAnimations: ["point", "idleDown"],
    featureId: "home",
    action: "routes the prototype state through the floating core monitor",
  },
  {
    roomId: "terminal-ring",
    roomName: "Terminal Ring",
    label: "testing the terminal ring",
    position: new THREE.Vector3(2.55, 0.04, -0.78),
    lookAt: new THREE.Vector3(3.35, 1.05, -0.92),
    animation: "point",
    freedomAnimations: ["point", "crouch", "idleSide"],
    featureId: "studio",
    action: "checks which terminal can safely drive her next self-test",
  },
  {
    roomId: "creator-light",
    roomName: "Creator Light",
    label: "watching the creator light",
    position: new THREE.Vector3(-1.35, 0.04, 2.78),
    lookAt: new THREE.Vector3(0, 1.55, 3.45),
    animation: "idleDown",
    freedomAnimations: ["idleDown", "waveDown"],
    featureId: "self",
    action: "uses the projector light as a clean focus point for Jason's presence",
  },
  {
    roomId: "entry",
    roomName: "Prototype Void",
    label: "orienting in the void",
    position: new THREE.Vector3(0.38, 0.04, 0.42),
    lookAt: new THREE.Vector3(0, 1.2, -0.8),
    animation: "idle",
    freedomAnimations: ["idleDown", "point"],
    action: "listens in the simplified testing space and chooses the next station",
  },
];

const prototypeAlpeccaRouteGuides: Record<string, AlpeccaRouteGuide> = {
  "void-core": {
    hall: new THREE.Vector3(0.18, 0.04, -0.05),
    door: new THREE.Vector3(-0.38, 0.04, -0.68),
    approach: new THREE.Vector3(-0.9, 0.04, -1.25),
  },
  "terminal-ring": {
    hall: new THREE.Vector3(0.18, 0.04, -0.05),
    door: new THREE.Vector3(1.42, 0.04, -0.38),
    approach: new THREE.Vector3(2.55, 0.04, -0.78),
  },
  "creator-light": {
    hall: new THREE.Vector3(0.18, 0.04, 0.28),
    door: new THREE.Vector3(-0.48, 0.04, 1.55),
    approach: new THREE.Vector3(-1.35, 0.04, 2.78),
  },
  entry: {
    hall: new THREE.Vector3(0.38, 0.04, 0.42),
    door: new THREE.Vector3(0.38, 0.04, 0.42),
    approach: new THREE.Vector3(0.38, 0.04, 0.42),
  },
};

let officeRooms: OfficeRoom[] = isPrototypeMode() ? prototypeRooms : hqOfficeRooms;
let entryRoom: OfficeRoom = isPrototypeMode() ? prototypeEntryRoom : hqEntryRoom;
let alpeccaExplorePoints: AlpeccaExplorePoint[] = isPrototypeMode() ? prototypeAlpeccaExplorePoints : hqAlpeccaExplorePoints;
let alpeccaRouteGuides: Record<string, AlpeccaRouteGuide> = isPrototypeMode() ? prototypeAlpeccaRouteGuides : hqAlpeccaRouteGuides;

const alpecca = {
  group: new THREE.Group(),
  animations: new Map<AlpeccaAnimationName, AlpeccaAnimation>(),
  loading: new Set<AlpeccaAnimationName>(),
  material: new THREE.MeshBasicMaterial({ transparent: true, alphaTest: 0.08, depthWrite: false, side: THREE.DoubleSide }),
  state: "idle" as AlpeccaAnimationName,
  sprite: null as THREE.Mesh<THREE.PlaneGeometry, THREE.MeshBasicMaterial> | null,
  transitionGhost: null as THREE.Mesh<THREE.PlaneGeometry, THREE.MeshBasicMaterial> | null,
  transitionGhostMaterial: null as THREE.MeshBasicMaterial | null,
  silhouette: null as THREE.Mesh<THREE.PlaneGeometry, THREE.MeshBasicMaterial> | null,
  glitchRed: null as THREE.Mesh<THREE.PlaneGeometry, THREE.MeshBasicMaterial> | null,
  glitchCyan: null as THREE.Mesh<THREE.PlaneGeometry, THREE.MeshBasicMaterial> | null,
  glitchScanline: null as THREE.Mesh<THREE.PlaneGeometry, THREE.MeshBasicMaterial> | null,
  depthProxy: null as THREE.Mesh<THREE.PlaneGeometry, THREE.MeshBasicMaterial> | null,
  hitTarget: null as THREE.Mesh<THREE.PlaneGeometry, THREE.MeshBasicMaterial> | null,
  heightRuler: null as THREE.Group | null,
  headLook: null as THREE.Group | null,
  headLookMaterial: null as THREE.MeshBasicMaterial | null,
  mouth: null as THREE.Mesh<THREE.PlaneGeometry, THREE.MeshBasicMaterial> | null,
  mouthMaterial: null as THREE.MeshBasicMaterial | null,
  ready: false,
  dialogueIndex: 0,
  patrolIndex: 0,
  intent: "idle" as AlpeccaIntent,
  perceptionTarget: "",
  waveTimer: 0,
  hasGreetedPlayer: false,
  attentionTimer: 0,
  expressiveTimer: 0,
  animationLockTimer: 0,
  startTimer: 2.6,
  dwellTimer: 0.9,
  walkSegmentTimer: 3.2,
  walkPauseTimer: 0,
  movementDirectivePending: false,
  exploreIndex: Math.max(0, alpeccaExplorePoints.findIndex((point) => point.roomId === "entry")),
  previousExploreIndex: 0,
  inspectTimer: 0,
  inspectNoticeTimer: 0,
  stuckTimer: 0,
  rerouteCooldown: 0,
  routeTargetIndex: -1,
  routeStep: 0,
  route: [] as THREE.Vector3[],
  lastX: 0,
  lastZ: 0,
  profileState: "idle" as AlpeccaAnimationName,
  activeFolder: "idle_right",
  moving: false,
  flipX: false,
  visualScale: 1,
  spriteY: 0.93,
  displayScale: 1,
  displaySpriteY: 0.93,
  stridePhase: 0,
  strideX: 0,
  bodyLean: 0,
  screenDirection: "down" as AlpeccaScreenDirection,
  directionCandidate: "down" as AlpeccaScreenDirection,
  directionCandidateFrames: 0,
  billboardYaw: 0,
  groundYaw: 0,
  avoidTimer: 0,
  shadow: null as THREE.Mesh<THREE.PlaneGeometry, THREE.MeshBasicMaterial> | null,
  chromaShadow: null as THREE.Mesh<THREE.PlaneGeometry, THREE.MeshBasicMaterial> | null,
  presenceGlow: null as THREE.Mesh<THREE.PlaneGeometry, THREE.MeshBasicMaterial> | null,
  presenceLight: null as THREE.PointLight | null,
  floorReflection: null as THREE.Mesh<THREE.PlaneGeometry, THREE.MeshBasicMaterial> | null,
  floorReflectionIntensity: 0,
  groundContactIntensity: 0,
  presenceIntensity: 0,
  leftFootShadow: null as THREE.Mesh<THREE.PlaneGeometry, THREE.MeshBasicMaterial> | null,
  rightFootShadow: null as THREE.Mesh<THREE.PlaneGeometry, THREE.MeshBasicMaterial> | null,
  footContact: "idle",
  mirrorReflection: 0,
  glitchTimer: 0,
  walkIntent: false,
  lastMovedDistance: 0,
  walkPlaybackRate: alpeccaWalkFrameRate,
  walkSpeed: 0,
  mouthOpen: 0,
  walkBob: 0,
  frameTime: 0,
  loopCount: 0,
  droppedFrames: 0,
  transitionTimer: 0,
  transitionDuration: 0.18,
  walkQaTimer: 0,
  walkQaIndex: 0,
  showcaseTimer: 0,
  showcaseState: "idleDown" as AlpeccaAnimationName,
  livePatrolSpeed: 0.26,
  selfReviewTargetRoom: "",
  terminalTargetId: "",
  terminalGesturePlayed: false,
  terminalGestureTimer: 0,
  terminalFeatureActivated: false,
  terminalContactAborted: false,
  terminalVrmTargetId: "",
  terminalInteractionPhase: "idle" as AlpeccaTerminalPhase | "idle",
  patrolPoints: alpeccaExplorePoints.map((point) => point.position),
};

const alpeccaAssetRoot = alpeccaAssetUrl("/assets/alpecca-optimized");
const alpeccaRuntimeMatrixManifestUrl = `${alpeccaAssetRoot}/runtime_matrix_manifest.json`;
let alpeccaRuntimeMatrixManifestStatus: AlpeccaMatrixManifestStatus = "pending";
let alpeccaRuntimeMatrixManifestError = "";
let alpeccaRuntimeMatrixRecords = new Map<string, AlpeccaRuntimeMatrixRecord>();
const alpeccaAnimationConfig: Record<AlpeccaAnimationName, AlpeccaAnimationConfig> = {
  idle: { folder: "idle_right", secondsPerFrame: 1 / 11 },
  walk: { folder: "walk_right", secondsPerFrame: alpeccaWalkSecondsPerFrame },
  wave: { folder: "Wave", secondsPerFrame: 1 / 12, loop: false },
  sit: { folder: "Sit", secondsPerFrame: 1 / 9 },
  point: { folder: "Point", secondsPerFrame: 1 / 13, loop: false },
  dance: { folder: "Dance", secondsPerFrame: 1 / 15 },
  victory: { folder: "Victory", secondsPerFrame: 1 / 13, loop: false },
  sleep: { folder: "Sleep", secondsPerFrame: 1 / 9 },
  pickup: { folder: "Pickup", secondsPerFrame: 1 / 12, loop: false },
  run: { folder: "run_right", secondsPerFrame: 1 / 16 },
  climb: { folder: "Climb", secondsPerFrame: 1 / 13, loop: false },
  crouch: { folder: "Crouch", secondsPerFrame: 1 / 10 },
  dash: { folder: "Dash", secondsPerFrame: 1 / 16, loop: false },
  jump: { folder: "jump_right", secondsPerFrame: 1 / 14, loop: false },
  jumpDown: { folder: "iso_jump_down_right", secondsPerFrame: 1 / 14, loop: false },
  jumpSide: { folder: "iso_jump_right_right", secondsPerFrame: 1 / 14, loop: false },
  jumpSoutheast: { folder: "iso_jump_southeast_right", secondsPerFrame: 1 / 14, loop: false },
  jumpUp: { folder: "iso_jump_up_right", secondsPerFrame: 1 / 14, loop: false },
  kneel: { folder: "Kneel", secondsPerFrame: 1 / 9 },
  sleepDown: { folder: "Sleep Down", secondsPerFrame: 1 / 9 },
  sleepNortheast: { folder: "Sleep Northeast", secondsPerFrame: 1 / 9 },
  sleepSoutheast: { folder: "Sleep Southeast", secondsPerFrame: 1 / 9 },
  sleepUp: { folder: "Sleep Up", secondsPerFrame: 1 / 9 },
  waveDown: { folder: "Wave Down", secondsPerFrame: 1 / 12, loop: false },
  waveNortheast: { folder: "Wave Northeast", secondsPerFrame: 1 / 12, loop: false },
  waveUp: { folder: "Wave Up", secondsPerFrame: 1 / 12, loop: false },
  idleDown: { folder: "iso_idle_down_right", secondsPerFrame: 1 / 11 },
  idleUp: { folder: "iso_idle_up_right", secondsPerFrame: 1 / 11 },
  idleSide: { folder: "iso_idle_right_right", secondsPerFrame: 1 / 11 },
  idleNortheast: { folder: "iso_idle_northeast_right", secondsPerFrame: 1 / 11 },
  idleSoutheast: { folder: "iso_idle_southeast_right", secondsPerFrame: 1 / 11 },
  talkDown: { folder: "gpt16_talk_down", secondsPerFrame: 1 / 12.5 },
  walkDown: { folder: "iso_walk_down_right", secondsPerFrame: alpeccaWalkSecondsPerFrame },
  walkUp: { folder: "iso_walk_up_right", secondsPerFrame: alpeccaWalkSecondsPerFrame },
  walkSide: { folder: "iso_walk_right_right", secondsPerFrame: alpeccaWalkSecondsPerFrame },
  walkLeft: { folder: "gpt16_walk_left_left", secondsPerFrame: alpeccaWalkSecondsPerFrame },
  walkNortheast: { folder: "iso_walk_northeast_right", secondsPerFrame: alpeccaWalkSecondsPerFrame },
  walkNorthwest: { folder: "gpt16_walk_northwest_left", secondsPerFrame: alpeccaWalkSecondsPerFrame },
  walkSoutheast: { folder: "iso_walk_southeast_right", secondsPerFrame: alpeccaWalkSecondsPerFrame },
  walkSouthwest: { folder: "gpt16_walk_southwest_left", secondsPerFrame: alpeccaWalkSecondsPerFrame },
  runDown: { folder: "iso_run_down_right", secondsPerFrame: 1 / 16 },
  runUp: { folder: "iso_run_up_right", secondsPerFrame: 1 / 16 },
  runSide: { folder: "iso_run_right_right", secondsPerFrame: 1 / 16 },
  runNortheast: { folder: "iso_run_northeast_right", secondsPerFrame: 1 / 16 },
  runSoutheast: { folder: "iso_run_southeast_right", secondsPerFrame: 1 / 16 },
};

const alpeccaMatrixFallbackStates: Record<AlpeccaMatrixAction, Record<AlpeccaViewHorizontalTier, AlpeccaAnimationName>> = {
  idle: {
    front: "idleDown",
    frontDiag: "idleSoutheast",
    side: "idleSide",
    backDiag: "idleNortheast",
    back: "idleUp",
  },
  listen: {
    front: "idleDown",
    frontDiag: "idleSoutheast",
    side: "idleSide",
    backDiag: "idleNortheast",
    back: "idleUp",
  },
  talk: {
    front: "talkDown",
    frontDiag: "talkDown",
    side: "talkDown",
    backDiag: "talkDown",
    back: "talkDown",
  },
  walk: {
    front: "walkDown",
    frontDiag: "walkSoutheast",
    side: "walkSide",
    backDiag: "walkNortheast",
    back: "walkUp",
  },
  wave: {
    front: "waveDown",
    frontDiag: "wave",
    side: "wave",
    backDiag: "waveNortheast",
    back: "waveUp",
  },
  inspect: {
    front: "point",
    frontDiag: "point",
    side: "point",
    backDiag: "kneel",
    back: "kneel",
  },
  careful: {
    front: "crouch",
    frontDiag: "crouch",
    side: "crouch",
    backDiag: "kneel",
    back: "kneel",
  },
  rest: {
    front: "sit",
    frontDiag: "sleepSoutheast",
    side: "sit",
    backDiag: "sleepNortheast",
    back: "sleepUp",
  },
  sleep: {
    front: "sleepDown",
    frontDiag: "sleepSoutheast",
    side: "sleepSoutheast",
    backDiag: "sleepNortheast",
    back: "sleepUp",
  },
};

function isAlpeccaSourceStatus(value: string): value is AlpeccaSourceStatus {
  return value === "approved" || value === "runtime-ok" || value === "qa-only" || value === "needs-regeneration";
}

function isAlpeccaVerticalTier(value: string): value is AlpeccaViewVerticalTier {
  return value === "low" || value === "eye" || value === "high";
}

function isAlpeccaHorizontalTier(value: string): value is AlpeccaViewHorizontalTier {
  return value === "front" || value === "frontDiag" || value === "side" || value === "backDiag" || value === "back";
}

function isAlpeccaRuntimeHorizontalTier(value: string) {
  return isAlpeccaHorizontalTier(value) || /^s(?:0?[0-9]|1[0-5])$/.test(value);
}

function isAlpeccaMatrixAction(value: string): value is AlpeccaMatrixAction {
  return value in alpeccaMatrixFallbackStates;
}

function normalizeAlpeccaLayerPlan(input: unknown, action: AlpeccaMatrixAction): AlpeccaRuntimeLayerPlan {
  const fallbackRoles: AlpeccaRuntimeLayerRole[] = ["base-body", "contact-shadow", "depth-proxy", "floor-reflection"];
  if (action === "talk" || action === "listen") fallbackRoles.splice(1, 0, "expression-overlay", "mouth-eye-overlay");
  const value = input && typeof input === "object" ? (input as Partial<AlpeccaRuntimeLayerPlan>) : {};
  const roles = Array.isArray(value.roles)
    ? value.roles.filter((role): role is AlpeccaRuntimeLayerRole =>
        role === "base-body" ||
        role === "expression-overlay" ||
        role === "mouth-eye-overlay" ||
        role === "contact-shadow" ||
        role === "depth-proxy" ||
        role === "floor-reflection",
      )
    : fallbackRoles;
  return {
    roles: roles.length ? Array.from(new Set(roles)) : fallbackRoles,
    expressionOverlay: Boolean(value.expressionOverlay ?? roles.includes("expression-overlay")),
    mouthEyeOverlay: Boolean(value.mouthEyeOverlay ?? roles.includes("mouth-eye-overlay")),
    contactShadow: Boolean(value.contactShadow ?? true),
    depthProxy: Boolean(value.depthProxy ?? true),
    floorReflection: Boolean(value.floorReflection ?? true),
    transitionSeconds: Number(value.transitionSeconds) || 0.065,
  };
}

function normalizeAlpeccaRuntimeMatrixRecord(input: Partial<AlpeccaRuntimeMatrixRecord>): AlpeccaRuntimeMatrixRecord | null {
  if (!input.key || !input.action || !input.verticalTier || !input.horizontalTier || !input.state || !input.folder) return null;
  if (!isAlpeccaMatrixAction(input.action)) return null;
  if (!isAlpeccaVerticalTier(input.verticalTier)) return null;
  if (!isAlpeccaRuntimeHorizontalTier(input.horizontalTier)) return null;
  if (!(input.state in alpeccaAnimationConfig)) return null;
  return {
    key: input.key,
    action: input.action,
    verticalTier: input.verticalTier,
    horizontalTier: input.horizontalTier,
    state: input.state,
    folder: input.folder,
    frameCount: Number(input.frameCount) || 0,
    sourceFamily: input.sourceFamily || alpeccaAnimationSourceFamily(input.folder),
    approvalStatus: isAlpeccaSourceStatus(input.approvalStatus || "") ? input.approvalStatus! : "runtime-ok",
    heightClass: input.heightClass,
    visualScale: Number(input.visualScale) || undefined,
    spriteY: Number(input.spriteY) || undefined,
    footAnchor: input.footAnchor || "bottom-center",
    contactFrameIndexes: Array.isArray(input.contactFrameIndexes) ? input.contactFrameIndexes.map(Number).filter(Number.isFinite) : [],
    layerPlan: normalizeAlpeccaLayerPlan(input.layerPlan, input.action),
    depthProxy: input.depthProxy || "alpha-silhouette-plane",
    notes: input.notes,
  };
}

async function loadAlpeccaRuntimeMatrixManifest() {
  alpeccaRuntimeMatrixManifestStatus = "pending";
  alpeccaRuntimeMatrixManifestError = "";
  try {
    const response = await fetch(alpeccaRuntimeMatrixManifestUrl, { cache: "no-cache" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const manifest = (await response.json()) as AlpeccaRuntimeMatrixManifest;
    const records = new Map<string, AlpeccaRuntimeMatrixRecord>();
    for (const rawRecord of manifest.records || []) {
      const record = normalizeAlpeccaRuntimeMatrixRecord(rawRecord);
      if (record) records.set(record.key, record);
    }
    if (records.size === 0) throw new Error("runtime matrix manifest contained no valid records");
    alpeccaRuntimeMatrixRecords = records;
    alpeccaRuntimeMatrixManifestStatus = "loaded";
  } catch (error) {
    alpeccaRuntimeMatrixRecords.clear();
    alpeccaRuntimeMatrixManifestStatus = "fallback";
    alpeccaRuntimeMatrixManifestError = error instanceof Error ? error.message : String(error);
    console.warn("Alpecca runtime matrix manifest unavailable; using local fallback map.", error);
  }
}

void loadAlpeccaRuntimeMatrixManifest();

const alpeccaAllAnimationStates: AlpeccaAnimationName[] = [
  "idle",
  "walk",
  "wave",
  "sit",
  "point",
  "dance",
  "victory",
  "sleep",
  "pickup",
  "run",
  "climb",
  "crouch",
  "dash",
  "jump",
  "jumpDown",
  "jumpSide",
  "jumpSoutheast",
  "jumpUp",
  "kneel",
  "sleepDown",
  "sleepNortheast",
  "sleepSoutheast",
  "sleepUp",
  "waveDown",
  "waveNortheast",
  "waveUp",
  "idleDown",
  "idleUp",
  "idleSide",
  "idleNortheast",
  "idleSoutheast",
  "talkDown",
  "walkDown",
  "walkUp",
  "walkSide",
  "walkLeft",
  "walkNortheast",
  "walkNorthwest",
  "walkSoutheast",
  "walkSouthwest",
  "runDown",
  "runUp",
  "runSide",
  "runNortheast",
  "runSoutheast",
];
window.__ALPECCA_ANIMATION_STATES__ = [...alpeccaAllAnimationStates];

const alpeccaCoreMovementStates: AlpeccaAnimationName[] = [
  "idleDown",
  "talkDown",
  "walkDown",
  "walkSide",
  "walkLeft",
  "idleSide",
  "walkUp",
  "walkNortheast",
  "walkNorthwest",
  "walkSoutheast",
  "walkSouthwest",
  "idleUp",
  "idleNortheast",
  "idleSoutheast",
];

const alpeccaStartupMovementStates: AlpeccaAnimationName[] = ["idleDown", "talkDown", "walkDown", "walkSide", "walkLeft"];

const alpeccaRareMovementStates: AlpeccaAnimationName[] = [
  "walk",
  "run",
  "runDown",
  "runUp",
  "runSide",
  "runNortheast",
  "runSoutheast",
  "dash",
  "jump",
  "jumpDown",
  "jumpSide",
  "jumpSoutheast",
  "jumpUp",
  "climb",
  "crouch",
];

const alpeccaRequiredMovementStates: AlpeccaAnimationName[] = [...alpeccaCoreMovementStates, ...alpeccaRareMovementStates];

const materials = {
  wall: new THREE.MeshStandardMaterial({ color: "#f6f7f3", roughness: 0.86 }),
  trim: new THREE.MeshStandardMaterial({ color: "#ffffff", roughness: 0.64 }),
  floor: new THREE.MeshStandardMaterial({ color: "#d8d6ce", roughness: 0.76 }),
  floorLine: new THREE.MeshBasicMaterial({ color: "#ffffff", transparent: true, opacity: 0.24, depthWrite: false }),
  tile: new THREE.MeshStandardMaterial({ color: "#e6ece9", roughness: 0.72 }),
  rug: new THREE.MeshStandardMaterial({ color: "#aeb9b5", roughness: 0.92 }),
  zone: new THREE.MeshStandardMaterial({ color: "#eef0ec", roughness: 0.86 }),
  zoneAlt: new THREE.MeshStandardMaterial({ color: "#e8eeee", roughness: 0.88 }),
  wallPanel: new THREE.MeshStandardMaterial({ color: "#e7ebe6", roughness: 0.82 }),
  accentPanel: new THREE.MeshStandardMaterial({ color: "#d9e5e2", roughness: 0.8 }),
  darkWood: new THREE.MeshStandardMaterial({ color: "#293332", roughness: 0.78 }),
  lightWood: new THREE.MeshStandardMaterial({ color: "#c5bdb2", roughness: 0.72 }),
  fabric: new THREE.MeshStandardMaterial({ color: "#6f7e7a", roughness: 0.92 }),
  metal: new THREE.MeshStandardMaterial({ color: "#aeb8b8", metalness: 0.12, roughness: 0.42 }),
  glass: new THREE.MeshStandardMaterial({ color: "#c9e2e4", transparent: true, opacity: 0.36, roughness: 0.08 }),
  glow: new THREE.MeshStandardMaterial({ color: "#f6f2d8", emissive: "#d7f2ff", emissiveIntensity: 0.78 }),
  lightPanel: new THREE.MeshBasicMaterial({ color: "#f4fbef", transparent: true, opacity: 0.76 }),
  keepsake: new THREE.MeshStandardMaterial({ color: "#d6b45f", metalness: 0.18, roughness: 0.35 }),
  screen: new THREE.MeshStandardMaterial({ color: "#11191b", emissive: "#7de7ff", emissiveIntensity: 0.46, roughness: 0.42 }),
  board: new THREE.MeshStandardMaterial({ color: "#283433", roughness: 0.88 }),
  paper: new THREE.MeshStandardMaterial({ color: "#f5f2e8", roughness: 0.88 }),
  plant: new THREE.MeshStandardMaterial({ color: "#3f795b", roughness: 0.84 }),
  flower: new THREE.MeshStandardMaterial({ color: "#cc6f8a", roughness: 0.76 }),
  pigeon: new THREE.MeshStandardMaterial({ color: "#858c91", roughness: 0.78 }),
  ceiling: new THREE.MeshStandardMaterial({ color: "#f6f6f1", roughness: 0.86 }),
  roof: new THREE.MeshStandardMaterial({ color: "#3f4747", roughness: 0.92 }),
  roofTrim: new THREE.MeshStandardMaterial({ color: "#5e6866", roughness: 0.78 }),
};

const aoMaterial = new THREE.MeshBasicMaterial({
  color: "#050606",
  transparent: true,
  opacity: 0.16,
  depthWrite: false,
});

function box(name: string, size: THREE.Vector3Tuple, pos: THREE.Vector3Tuple, mat: THREE.Material, cast = true, receive = true) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), mat);
  mesh.name = name;
  mesh.position.set(...pos);
  mesh.castShadow = cast;
  mesh.receiveShadow = receive;
  scene.add(mesh);
  return mesh;
}

function cylinder(name: string, radius: number, depth: number, pos: THREE.Vector3Tuple, mat: THREE.Material, segments = 32) {
  const mesh = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius, depth, segments), mat);
  mesh.name = name;
  mesh.position.set(...pos);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  scene.add(mesh);
  return mesh;
}

function addCollider(centerX: number, centerZ: number, sizeX: number, sizeZ: number) {
  walls.push({
    minX: centerX - sizeX / 2,
    maxX: centerX + sizeX / 2,
    minZ: centerZ - sizeZ / 2,
    maxZ: centerZ + sizeZ / 2,
  });
}

function addWall(name: string, centerX: number, centerZ: number, sizeX: number, sizeZ: number) {
  box(name, [sizeX, 2.8, sizeZ], [centerX, 1.4, centerZ], materials.wall);
  addCollider(centerX, centerZ, sizeX, sizeZ);
}

function addFurnitureCollider(centerX: number, centerZ: number, sizeX: number, sizeZ: number) {
  addCollider(centerX, centerZ, sizeX, sizeZ);
}

function addExteriorBoundaryColliders() {
  addCollider(0, -6.18, 16.4, 0.28);
  addCollider(0, 6.18, 16.4, 0.28);
  addCollider(-8.18, 0, 0.28, 12.4);
  addCollider(8.18, 0, 0.28, 12.4);
  addCollider(0, 5.12, 16.4, 0.48);
}

function addExteriorWallSealPanels() {
  box("north exterior wall seal", [16.25, 2.9, 0.08], [0, 1.45, -6.03], materials.wall, false, true);
  box("south exterior wall seal", [16.25, 2.9, 0.08], [0, 1.45, 6.03], materials.wall, false, true);
  box("west exterior wall seal", [0.08, 2.9, 12.15], [-8.03, 1.45, 0], materials.wall, false, true);
  box("east exterior wall seal", [0.08, 2.9, 12.15], [8.03, 1.45, 0], materials.wall, false, true);
  box("north upper wall seal", [16.2, 0.36, 0.2], [0, 2.96, -5.82], materials.trim, false, true);
  box("south upper wall seal", [16.2, 0.36, 0.2], [0, 2.96, 5.82], materials.trim, false, true);
  box("west upper wall seal", [0.2, 0.36, 12.1], [-7.82, 2.96, 0], materials.trim, false, true);
  box("east upper wall seal", [0.2, 0.36, 12.1], [7.82, 2.96, 0], materials.trim, false, true);
}

function addInteriorWallSkins() {
  box("north interior continuous wall skin", [15.75, 2.72, 0.05], [0, 1.39, -5.58], materials.wall, false, true);
  box("south interior continuous wall skin", [15.75, 2.72, 0.05], [0, 1.39, 5.58], materials.wall, false, true);
  box("west interior continuous wall skin", [0.05, 2.72, 11.55], [-7.58, 1.39, 0], materials.wall, false, true);
  box("east interior continuous wall skin", [0.05, 2.72, 11.55], [7.58, 1.39, 0], materials.wall, false, true);

  box("north baseboard", [15.35, 0.16, 0.07], [0, 0.22, -5.43], materials.trim, false, true);
  box("south baseboard", [15.35, 0.16, 0.07], [0, 0.22, 5.43], materials.trim, false, true);
  box("west baseboard", [0.07, 0.16, 11.15], [-7.43, 0.22, 0], materials.trim, false, true);
  box("east baseboard", [0.07, 0.16, 11.15], [7.43, 0.22, 0], materials.trim, false, true);

  box("north ceiling cove", [15.45, 0.12, 0.08], [0, 2.72, -5.43], materials.trim, false, true);
  box("south ceiling cove", [15.45, 0.12, 0.08], [0, 2.72, 5.43], materials.trim, false, true);
  box("west ceiling cove", [0.08, 0.12, 11.25], [-7.43, 2.72, 0], materials.trim, false, true);
  box("east ceiling cove", [0.08, 0.12, 11.25], [7.43, 2.72, 0], materials.trim, false, true);

  for (const [x, z] of [
    [-7.45, -5.45],
    [7.45, -5.45],
    [-7.45, 5.45],
    [7.45, 5.45],
  ] as Array<[number, number]>) {
    box("sealed interior corner post", [0.2, 2.72, 0.2], [x, 1.39, z], materials.trim, false, true);
  }
}

function addInteriorDividerTrim() {
  const trimRuns: Array<[string, THREE.Vector3Tuple, THREE.Vector3Tuple]> = [
    ["bedroom divider baseboard", [0.07, 0.14, 3.85], [-1.38, 0.21, -3.65]],
    ["living divider baseboard", [0.07, 0.14, 2.5], [-1.38, 0.21, 2.5]],
    ["kitchen divider baseboard", [0.07, 0.14, 3.95], [2.22, 0.21, 1.55]],
    ["bath divider baseboard", [0.07, 0.14, 3.2], [2.22, 0.21, -4.1]],
    ["hall left baseboard", [4.0, 0.14, 0.07], [-5.7, 0.21, -1.08]],
    ["hall right baseboard", [4.45, 0.14, 0.07], [5.45, 0.21, -1.08]],
    ["bedroom divider cap", [0.08, 0.1, 3.95], [-1.38, 2.72, -3.65]],
    ["living divider cap", [0.08, 0.1, 2.6], [-1.38, 2.72, 2.5]],
    ["kitchen divider cap", [0.08, 0.1, 4.05], [2.22, 2.72, 1.55]],
    ["bath divider cap", [0.08, 0.1, 3.3], [2.22, 2.72, -4.1]],
    ["library doorway left jamb trim", [0.11, 2.55, 0.34], [-3.55, 1.34, -1.25]],
    ["library doorway right jamb trim", [0.11, 2.55, 0.34], [-1.55, 1.34, -1.25]],
    ["self design upper jamb trim", [0.11, 2.55, 0.34], [-1.55, 1.34, 1.12]],
    ["hq doorway jamb trim", [0.11, 2.55, 0.34], [-1.55, 1.34, 3.86]],
    ["observatory doorway jamb trim", [0.11, 2.55, 0.34], [2.05, 1.34, 3.76]],
    ["workshop inner wall jamb trim", [0.11, 2.55, 0.34], [3.05, 1.34, -1.25]],
    ["workshop doorway jamb trim", [0.11, 2.55, 0.34], [2.05, 1.34, -2.28]],
  ];

  for (const [name, size, pos] of trimRuns) box(name, size, pos, materials.trim, false, true);
}

function addWallGapSeals() {
  const seals: Array<[string, THREE.Vector3Tuple, THREE.Vector3Tuple]> = [
    ["north wall center gap seal", [1.95, 2.78, 0.09], [-0.22, 1.39, -5.86]],
    ["south wall right seam seal", [0.24, 2.78, 0.09], [1.95, 1.39, 5.86]],
    ["library cross wall inner return", [0.22, 2.72, 0.28], [-3.55, 1.36, -1.25]],
    ["workshop cross wall inner return", [0.22, 2.72, 0.28], [3.05, 1.36, -1.25]],
    ["bedroom divider end return", [0.32, 2.72, 0.18], [-1.55, 1.36, -1.5]],
    ["living divider end return", [0.32, 2.72, 0.18], [-1.55, 1.36, 1.05]],
    ["bath divider end return", [0.32, 2.72, 0.18], [2.05, 1.36, -2.28]],
    ["kitchen divider end return", [0.32, 2.72, 0.18], [2.05, 1.36, -0.6]],
  ];
  for (const [name, size, pos] of seals) box(name, size, pos, materials.wall, false, true);
}

function addModernWallPanels() {
  const panels: Array<[string, THREE.Vector3Tuple, THREE.Vector3Tuple, THREE.Material]> = [
    ["hq control clean rear wall panel", [3.75, 1.34, 0.055], [-4.62, 1.46, 5.39], materials.wallPanel],
    ["library clean west wall panel", [0.055, 1.54, 3.55], [-7.36, 1.36, -3.45], materials.wallPanel],
    ["self design mirror wall panel", [0.055, 1.72, 2.04], [-7.36, 1.38, 0.46], materials.wallPanel],
    ["observatory clean rear wall panel", [3.95, 1.34, 0.055], [5.1, 1.46, 5.39], materials.wallPanel],
    ["workshop clean east wall panel", [0.055, 1.48, 3.55], [7.36, 1.36, -3.6], materials.wallPanel],
    ["entry spine clean north panel", [1.26, 1.22, 0.05], [0.25, 1.34, -5.36], materials.accentPanel],
    ["entry spine clean south panel", [1.26, 1.22, 0.05], [0.25, 1.34, 5.36], materials.accentPanel],
  ];
  for (const [name, size, pos, mat] of panels) box(name, size, pos, mat, false, true);

  const seamCaps: Array<[string, THREE.Vector3Tuple, THREE.Vector3Tuple]> = [
    ["library divider flush seam cap", [0.08, 2.52, 0.34], [-1.42, 1.34, -1.12]],
    ["self design upper flush seam cap", [0.08, 2.52, 0.34], [-1.42, 1.34, 1.18]],
    ["observatory divider flush seam cap", [0.08, 2.52, 0.34], [2.18, 1.34, 1.22]],
    ["workshop divider flush seam cap", [0.08, 2.52, 0.34], [2.18, 1.34, -1.18]],
  ];
  for (const [name, size, pos] of seamCaps) box(name, size, pos, materials.trim, false, true);
}

function addDoorFrame(name: string, pos: THREE.Vector3Tuple, yaw: number, width = 1.72) {
  const frame = new THREE.Group();
  frame.name = `${name} frame`;
  frame.position.set(pos[0], 0, pos[2]);
  frame.rotation.y = yaw;
  scene.add(frame);
  groupBox(frame, [0.1, 2.48, 0.08], [0, 1.24, -width / 2], materials.trim);
  groupBox(frame, [0.1, 2.48, 0.08], [0, 1.24, width / 2], materials.trim);
  groupBox(frame, [0.12, 0.13, width + 0.14], [0, 2.45, 0], materials.trim);
  groupBox(frame, [0.03, 0.012, width + 0.08], [0, 0.035, 0], materials.floorLine);
}

function register(item: Interactable) {
  interactables.push(item);
  item.root.traverse((child) => {
    if ((child as THREE.Mesh).isMesh) {
      interactableMeshes.set(child.uuid, item);
      interactableObjects.push(child);
    }
  });
}

function showMessage(text: string, duration = 2.6) {
  messageEl.textContent = text;
  messageEl.classList.add("visible");
  lastMessageTimer = duration;
}

type AlpeccaLogRole = "Player" | "Alpecca" | "Room" | "System";
const alpeccaInteractionLog: Array<{ role: AlpeccaLogRole; text: string }> = [];
let alpeccaActivityHoldUntil = 0;

function escapeHudText(text: string) {
  return text.replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char] || char);
}

function appendAlpeccaLog(role: AlpeccaLogRole, text: string) {
  const clean = text.trim().replace(/\s+/g, " ");
  if (!clean) return;
  alpeccaInteractionLog.push({ role, text: clean.slice(0, 180) });
  alpeccaInteractionLog.splice(0, Math.max(0, alpeccaInteractionLog.length - 5));
  alpeccaInteractionLogEl.innerHTML = alpeccaInteractionLog
    .map((entry) => `<p><b>${entry.role}</b><span>${escapeHudText(entry.text)}</span></p>`)
    .join("");
}

function setAlpeccaIntent(intent: AlpeccaIntent, target = "") {
  alpecca.intent = intent;
  if (target) alpecca.perceptionTarget = target;
  document.body.dataset.alpeccaIntent = intent;
  document.body.dataset.alpeccaPerceptionTarget = alpecca.perceptionTarget;
}

function setAlpeccaActivity(text: string, tone: "idle" | "observe" | "think" | "move" | "create" = "idle", holdSeconds = 4) {
  alpeccaActivityEl.textContent = text;
  alpeccaActivityEl.dataset.tone = tone;
  chipLoop.dataset.tone = tone;
  chipLoop.title = text;
  document.body.dataset.alpeccaActivity = text;
  alpeccaActivityHoldUntil = performance.now() + holdSeconds * 1000;
}

function setAlpeccaLivingState(loop?: AlpeccaAiMessage["living_loop"], fallbackText = "") {
  const intentName =
    loop?.intent?.name ||
    (typeof loop?.phase === "string" ? loop.phase.replace(/_/g, " ") : "") ||
    "questioning";
  const roomName = loop?.room?.name || currentOfficeRoom().name;
  const question = loop?.question || fallbackText || "What should I understand next from this room?";
  const creatorSeen = loop?.creator
    ? loop.creator.fresh_evidence
      ? `Fresh ${loop.creator.name || "creator"} context.`
      : `Creator context: ${loop.creator.speaker || "unknown"}.`
    : "";
  alpeccaLivingIntentEl.textContent = `${intentName} · ${roomName}`;
  alpeccaLivingQuestionEl.textContent = creatorSeen ? `${question} ${creatorSeen}` : question;
  const activated = loop?.activated_system?.label
    ? `Activated ${loop.activated_system.label}${loop.activated_system.status ? ` (${loop.activated_system.status})` : ""}`
    : "";
  const systemSummary = loop?.activated_system?.summary ? `${loop.activated_system.summary} ` : "";
  const feedback = loop?.self_feedback;
  const feedbackSummary = feedback?.noticed || feedback?.learned || feedback?.next_action
    ? [
        feedback?.noticed ? `Noticed: ${feedback.noticed}` : "",
        feedback?.learned ? `Learned: ${feedback.learned}` : "",
        feedback?.next_action ? `Next: ${feedback.next_action}` : "",
      ].filter(Boolean).join(" ")
    : "";
  if (activated) alpeccaLivingIntentEl.textContent = [intentName, roomName, activated].join(" - ");
  const questionLine = question ? `Q: ${question}` : "";
  if (feedbackSummary) {
    alpeccaLivingQuestionEl.textContent = [questionLine, feedbackSummary, creatorSeen].filter(Boolean).join(" ");
  } else if (systemSummary) {
    alpeccaLivingQuestionEl.textContent = [questionLine || systemSummary, questionLine ? systemSummary : "", creatorSeen].filter(Boolean).join(" ");
  }
  chipLoopText.textContent = intentName;
  alpeccaLivingStateEl.dataset.intent = intentName;
  alpeccaLivingStateEl.dataset.system = loop?.activated_system?.id || "";
  alpeccaLivingStateEl.dataset.nextAction = loop?.next_action?.action || "";
  alpeccaLivingStateEl.dataset.question = question;
  document.body.dataset.alpeccaLivingIntent = intentName;
  document.body.dataset.alpeccaLivingQuestion = question;
  document.body.dataset.alpeccaLivingNextAction = loop?.next_action?.action || "";
  assimilateAlpeccaLivingLoopMemory(loop, question, roomName, fallbackText);
}

function assimilateAlpeccaLivingLoopMemory(loop?: AlpeccaAiMessage["living_loop"], question = "", roomName = "", fallbackText = "") {
  if (!loop) return;
  const roomId = loop.room?.id || livingLoopTargetRoomId(loop) || currentOfficeRoom().id;
  const room = officeRooms.find((item) => item.id === roomId) ?? currentOfficeRoom();
  const memory = environmentMemoryForRoom(room.id);
  const system = loop.activated_system?.label || loop.activated_system?.id || "living loop";
  const summary = loop.activated_system?.summary || fallbackText || loop.line || question || "";
  const previousQuestion = memory.lastQuestion;
  memory.observations += 1;
  memory.online = true;
  memory.lastAction = `Living loop activated ${system}`;
  memory.lastSource = "Alpecca core living loop";
  memory.lastSeen = summary.slice(0, 260);
  memory.lastQuestion = question || previousQuestion;
  memory.confidence = THREE.MathUtils.clamp(memory.confidence + 0.16 + (loop.memory_id ? 0.08 : 0) + (loop.journal_id ? 0.06 : 0), 0, 1);
  saveAlpeccaAppMemory();
  pulseAlpeccaEnvironmentModel(room.id, 4.6);
  pulseAlpeccaRoomDevice(room.id, 2.8);
  const trace = alpeccaMemoryTraces.get(room.id);
  if (trace) {
    trace.visits += 1;
    trace.pulseTimer = Math.max(trace.pulseTimer, 4.2);
    trace.note = `${room.name} living loop ${trace.visits}: ${summary || question || "Alpecca updated this room from the core."}`;
  }
  const journalNote = `Living loop memory: ${room.name} activated ${system}; question=${memory.lastQuestion || "none"}; memory=${loop.memory_id || "local"}; journal=${loop.journal_id || "local"}.`;
  if (!alpeccaAppMemory.journal.includes(journalNote)) rememberAlpeccaJournalEntry(journalNote);
}

function pulseAlpeccaActivatedSystem(systemId = "") {
  if (systemId === "memory") pulseAlpeccaSourceTerminal("memory", 3.2, true);
  else if (systemId === "self_review") pulseAlpeccaSourceTerminal("self", 3.2, true);
  else if (systemId === "room_review" || systemId === "perception") pulseAlpeccaRoomDetails(currentOfficeRoom().id);
  else if (systemId === "voice") pulseAlpeccaSourceTerminal("home", 3.2, true);
  else if (systemId === "mindscape") pulseAlpeccaImprovementQueue(3.2);
  pulseAlpeccaSourceDashboard("", 2.6);
}

function livingLoopTargetRoomId(loop?: AlpeccaAiMessage["living_loop"]) {
  const systemId = loop?.activated_system?.id || "";
  if (systemId === "memory") return "library";
  if (systemId === "self_review") return "self-design";
  if (systemId === "voice" || systemId === "mindscape") return "hq-control";
  const suppliedRoom = String(loop?.room?.id || loop?.room?.name || "").trim().toLowerCase();
  const resolvedRoom = officeRooms.find(
    (room) => room.id.toLowerCase() === suppliedRoom || room.name.toLowerCase() === suppliedRoom,
  );
  if (systemId === "perception") return resolvedRoom?.id || currentOfficeRoom().id;
  if (systemId === "room_review") return resolvedRoom?.id || currentOfficeRoom().id;
  return resolvedRoom?.id || "hq-control";
}

function featureForLivingLoop(loop?: AlpeccaAiMessage["living_loop"]) {
  const systemId = loop?.activated_system?.id || "";
  const roomId = livingLoopTargetRoomId(loop);
  if (systemId === "memory") return "memory";
  if (systemId === "self_review") return "self";
  if (systemId === "voice" || systemId === "mindscape" || roomId === "hq-control") return "home";
  if (roomId === "library") return "memory";
  if (roomId === "workshop") return "studio";
  if (roomId === "self-design") return "self";
  if (roomId === "observatory") return "soul";
  return "";
}

function routeAlpeccaToLivingLoopTarget(loop?: AlpeccaAiMessage["living_loop"]) {
  const roomId = livingLoopTargetRoomId(loop);
  const index = alpeccaExplorePoints.findIndex((point) => point.roomId === roomId);
  if (index < 0) return;
  // House movement is a projection of an actual CoreMind living-loop result.
  // Do not fall back to a random patrol after arrival: the next movement must
  // wait for another grounded core directive.
  alpecca.movementDirectivePending = true;
  alpecca.selfReviewTargetRoom = "";
  alpecca.previousExploreIndex = alpecca.exploreIndex;
  alpecca.exploreIndex = index;
  alpecca.routeTargetIndex = -1;
  alpecca.routeStep = 0;
  alpecca.route.length = 0;
  alpecca.walkPauseTimer = 0;
  alpecca.dwellTimer = 0;
  alpecca.inspectTimer = 0;
  alpecca.inspectNoticeTimer = 0;
  clearAlpeccaTerminalInteraction();
  setAlpeccaIntent("observing", alpeccaExplorePoints[index].roomName);
}

function alpeccaConnectionLabel() {
  if (alpeccaAiStatus === "live") return alpeccaAiLlmOnline ? "Live" : "Live Basic";
  if (alpeccaAiStatus === "connecting") return "Connecting";
  if (alpeccaAiStatus === "token") return "Reconnect";
  return "Offline";
}

function alpeccaProfileDetailLabel(detail = "") {
  const connection = alpeccaConnectionLabel();
  const mood = alpeccaAiStatus === "live" && alpeccaAiMood && alpeccaAiMood !== "offline" ? alpeccaAiMood : "";
  const cleanDetail = detail.replace(/\b(content|offline)\b/gi, "").replace(/\s*\/\s*\/\s*/g, " / ").trim();
  return [connection, mood, cleanDetail].filter(Boolean).join(" / ");
}

function alpeccaModelUseLabel(use: AlpeccaModelUse) {
  if (!use || !use.backend) return alpeccaAiLlmOnline ? "Local" : "Basic";
  if (use.fallback || use.used_tier === "fallback") return "Basic";
  const backend = String(use.backend || "").toLowerCase();
  if (use.used_tier === "deep" || backend === "zerogpu") return "Deep";
  if (backend === "ollama") return use.used_tier === "fast" ? "Fast Local" : "Local";
  if (backend === "hf") return "HF";
  return backend ? backend.toUpperCase() : "Local";
}

function updateCoreStatusLabels() {
  const modelLabel = alpeccaModelUseLabel(alpeccaAiModelUse);
  const status =
    alpeccaAiStatus === "live"
      ? `${alpeccaConnectionLabel()} / ${modelLabel}${alpeccaAiMood && alpeccaAiMood !== "offline" ? ` / ${alpeccaAiMood}` : ""}`
      : alpeccaAiStatus === "token"
        ? "Reconnect"
        : "Offline";
  alpeccaProfileConnection.textContent = status;
  alpeccaProfileConnection.dataset.status = alpeccaAiStatus;
  alpeccaProfileConnection.title = alpeccaAiModelUse.model
    ? `${alpeccaAiModelUse.backend || ""} ${alpeccaAiModelUse.used_tier || ""}: ${alpeccaAiModelUse.model}`
    : "";
  calmModeToggle.textContent = `Calm mode: ${alpeccaAppMemory.visualCalmMode ? "On" : "Off"}`;
  hudModeToggle.textContent = `HUD: ${alpeccaAppMemory.hudMode === "auto" ? "Auto" : alpeccaAppMemory.hudMode === "minimal" ? "Minimal" : "Full"}`;
  embodimentToggle.textContent =
    alpeccaEmbodimentState === "vrm"
      ? "Body: 3D model"
      : alpeccaEmbodimentState === "loading"
        ? "Body: loading 3D…"
        : "Body: 2D sprite";
  embodimentStatus.textContent =
    alpeccaVrmStatusDetail ||
    (alpeccaEmbodimentState === "vrm"
      ? "3D body active (experimental); tap to return to 2D"
      : "3D body: experimental, tap to load her VRM");
}

function updateDefaultAlpeccaActivity() {
  if (performance.now() < alpeccaActivityHoldUntil) return;
  if (alpeccaAiAwaitingReply) {
    setAlpeccaIntent("thinking", "live core");
    setAlpeccaActivity("Alpecca is thinking through the live core.", "think", 1);
    return;
  }
  if (!alpeccaChat.classList.contains("hidden")) {
    setAlpeccaIntent(isAlpeccaTalking() ? "replying" : "listening", "player");
    setAlpeccaActivity(isAlpeccaTalking() ? "Alpecca is replying to you." : "Alpecca is listening to you.", "think", 1);
    return;
  }
  if (alpecca.inspectTimer > 0) {
    const point = alpeccaExplorePoints[alpecca.exploreIndex % alpeccaExplorePoints.length];
    setAlpeccaIntent("inspecting", point.roomName);
    setAlpeccaActivity(`Alpecca is ${point.label}.`, "observe", 1);
    return;
  }
  if (alpecca.moving) {
    const point = alpeccaExplorePoints[alpecca.exploreIndex % alpeccaExplorePoints.length];
    setAlpeccaIntent("approaching", point.roomName);
    setAlpeccaActivity(`Alpecca is walking toward ${point.roomName}.`, "move", 1);
    return;
  }
  setAlpeccaIntent("idle", "house");
  setAlpeccaActivity("Alpecca is listening to the house.", "idle", 1);
}

function roomContains(room: OfficeRoom, x: number, z: number) {
  return x >= room.bounds.minX && x <= room.bounds.maxX && z >= room.bounds.minZ && z <= room.bounds.maxZ;
}

function currentOfficeRoom() {
  return officeRooms.find((room) => roomContains(room, camera.position.x, camera.position.z)) ?? entryRoom;
}

function officeRoomAtPosition(x: number, z: number) {
  return officeRooms.find((room) => roomContains(room, x, z)) ?? entryRoom;
}

function roomIsActive(room: OfficeRoom) {
  return room.id === "entry" || activeRoomIds.has(room.stationId);
}

function activeRoomTotal() {
  return officeRooms.length;
}

function activeEnvironmentLabel() {
  return isPrototypeMode() ? "Alpecca Void" : "AI Office HQ";
}

function activeEnvironmentObjective() {
  if (isPrototypeMode()) return "Alpecca's void: her main embodied space - presence, senses, and clean sight lines.";
  return "AI Office HQ - a working place in her void: bring all five rooms online.";
}

function updateEnvironmentModeUi() {
  environmentModeLabel.textContent = isPrototypeMode()
    ? "Environment: Alpecca Void (core)"
    : "Environment: AI Office HQ (in the void)";
  environmentModeToggle.textContent = isPrototypeMode() ? "Enter the AI Office HQ" : "Return to the Void";
  masterPlanStageLabel.textContent = "Master plan: Phase 8 RSI verified; operational soak pending; Phase 9 active";
  alpeccaAssetModeLabel.textContent = `Art assets: ${alpeccaArtAssetMode === "huggingface-runtime" ? "Hugging Face runtime" : "Local fallback"}`;
  alpeccaAssetModeLabel.dataset.status = alpeccaArtAssetMode === "huggingface-runtime" ? "live" : "offline";
  objectiveEl.textContent = activeEnvironmentObjective();
  const counter = foundEl.parentElement!;
  counter.textContent = "";
  foundEl.textContent = String(activatedRooms);
  counter.append(foundEl, `/${activeRoomTotal()}`);
  chipMission.textContent = `${activatedRooms}/${activeRoomTotal()}`;
}

function updateRoomPanel(force = false) {
  const room = currentOfficeRoom();
  if (!force && room.id === currentRoomId && roomPanelTimer > 0) return;

  currentRoomId = room.id;
  roomPanelTimer = 0.2;
  chipRoom.textContent = room.name;
  roomNameEl.textContent = room.name;
  roomPurposeEl.textContent = room.purpose;
  const active = roomIsActive(room);
  roomStatusEl.textContent =
    room.id === "entry" ? `${activatedRooms}/${activeRoomTotal()} systems online` : active ? `${room.system} online` : `${room.system} offline`;
  roomPanel.dataset.status = active ? "online" : "offline";
}

function activeRoomSummary() {
  return officeRooms
    .map((room) => `${room.name}: ${roomIsActive(room) ? "online" : "offline"}`)
    .join("; ");
}

function alpeccaContextPrefix() {
  const room = currentOfficeRoom();
  return `Game context: player is in ${room.name} inside ${activeEnvironmentLabel()}. Room purpose: ${room.purpose}. Progress ${activatedRooms}/${activeRoomTotal()}. Systems: ${activeRoomSummary()}.`;
}

function alpeccaSurfaceContextSnapshot() {
  const playerRoom = currentOfficeRoom();
  const alpeccaRoom = officeRoomAtPosition(alpecca.group.position.x, alpecca.group.position.z);
  const activePanels = [
    !alpeccaChat.classList.contains("hidden") ? `profile:${alpeccaProfileMode}` : "",
    !alpeccaWorkshop.classList.contains("hidden") ? "workshop" : "",
    alpeccaActiveProfileFeature ? `feature:${alpeccaActiveProfileFeature}` : "",
  ].filter(Boolean);
  const path = `${window.location.pathname}${window.location.search}`;
  const environment = activeEnvironmentLabel();
  const player = `${camera.position.x.toFixed(1)},${camera.position.z.toFixed(1)}`;
  const npc = `${alpecca.group.position.x.toFixed(1)},${alpecca.group.position.z.toFixed(1)}`;
  const key = [
    environment,
    playerRoom.id,
    alpeccaRoom.id,
    activePanels.join(",") || "no-panel",
    alpecca.intent,
    alpecca.perceptionTarget || "no-target",
    path.includes("environment=prototype") ? "prototype-url" : "default-url",
    player,
    npc,
  ].join("|");
  return {
    key,
    playerRoom,
    alpeccaRoom,
    environment,
    activePanels,
    path,
    content:
      `House presence: Alpecca is embodied in ${environment}. ` +
      `The player is in ${playerRoom.name}; Alpecca is near ${alpeccaRoom.name}. ` +
      `Active surface: House HQ, the internal view of Alpecca's mind (${isPrototypeMode() ? "void core" : "AI Office HQ"}). ` +
      `Visible panels: ${activePanels.join(", ") || "none"}. ` +
      `Current target: ${alpecca.perceptionTarget || "none"}. ` +
      `Progress ${activatedRooms}/${activeRoomTotal()} systems online.`,
  };
}

function sendAlpeccaPresenceContext(force = false) {
  if (alpeccaAiStatus !== "live" || !alpeccaAiBaseUrl || alpeccaAiAwaitingReply) return;
  const snapshot = alpeccaSurfaceContextSnapshot();
  if (!force && snapshot.key === alpeccaLastPresenceContextKey) return;
  alpeccaLastPresenceContextKey = snapshot.key;
  void alpeccaBackendFetch(alpeccaUrlWithParams(`${alpeccaAiBaseUrl}/cognition/observe`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source: "house-presence",
      room: snapshot.playerRoom.name,
      content: snapshot.content,
      confidence: 0.88,
      novelty: force ? 0.6 : 0.32,
      metadata: {
        app_surface: "house-hq",
        environment_mode: currentEnvironmentMode,
        environment_label: snapshot.environment,
        player_room_id: snapshot.playerRoom.id,
        alpecca_room_id: snapshot.alpeccaRoom.id,
        path: snapshot.path,
        active_panels: snapshot.activePanels,
        player_position: {
          x: Number(camera.position.x.toFixed(3)),
          y: Number(camera.position.y.toFixed(3)),
          z: Number(camera.position.z.toFixed(3)),
        },
        alpecca_position: {
          x: Number(alpecca.group.position.x.toFixed(3)),
          y: Number(alpecca.group.position.y.toFixed(3)),
          z: Number(alpecca.group.position.z.toFixed(3)),
        },
        current_intent: alpecca.intent,
        perception_target: alpecca.perceptionTarget,
      },
    }),
  }).catch(() => undefined);
}

function updateAlpeccaPresenceContext(dt: number) {
  if (alpeccaPresenceContextTimer > 0) alpeccaPresenceContextTimer = Math.max(0, alpeccaPresenceContextTimer - dt);
  if (alpeccaPresenceContextTimer > 0) return;
  alpeccaPresenceContextTimer = isPrototypeMode() ? 9 : 13;
  sendAlpeccaPresenceContext(false);
}

function sanitizeAlpeccaEnvironmentRooms(raw: unknown) {
  const rooms: Record<string, AlpeccaEnvironmentRoomMemory> = {};
  if (!raw || typeof raw !== "object") return rooms;
  for (const [roomId, value] of Object.entries(raw as Record<string, unknown>)) {
    if (!value || typeof value !== "object") continue;
    const item = value as Partial<AlpeccaEnvironmentRoomMemory>;
    rooms[roomId] = {
      observations: Math.max(0, Math.floor(item.observations ?? 0)),
      online: Boolean(item.online),
      lastAction: typeof item.lastAction === "string" ? item.lastAction : "No observation recorded.",
      lastSource: typeof item.lastSource === "string" ? item.lastSource : "unknown",
      lastSeen: typeof item.lastSeen === "string" ? item.lastSeen : "",
      lastQuestion: typeof item.lastQuestion === "string" ? item.lastQuestion : "",
      confidence: THREE.MathUtils.clamp(Number(item.confidence) || 0, 0, 1),
    };
  }
  return rooms;
}

function loadAlpeccaAppMemory(): AlpeccaAppMemory {
  try {
    const raw = localStorage.getItem(alpeccaAppMemoryStorageKey);
    if (!raw) throw new Error("no app memory");
    const parsed = JSON.parse(raw) as Partial<AlpeccaAppMemory>;
    return {
      entries: Math.max(0, Math.floor(parsed.entries ?? 0)),
      returns: Math.max(0, Math.floor(parsed.returns ?? 0)),
      recursiveDepth: Math.max(0, Math.floor(parsed.recursiveDepth ?? 0)),
      selfAudits: Math.max(0, Math.floor(parsed.selfAudits ?? 0)),
      improvementRuns: Math.max(0, Math.floor(parsed.improvementRuns ?? 0)),
      curiositySweeps: Math.max(0, Math.floor(parsed.curiositySweeps ?? 0)),
      identityReflections: Math.max(0, Math.floor(parsed.identityReflections ?? 0)),
      clarityFeedbacks: Math.max(0, Math.floor(parsed.clarityFeedbacks ?? 0)),
      visualCalmMode: parsed.visualCalmMode !== false,
      hudMode: parsed.hudMode === "minimal" || parsed.hudMode === "full" ? parsed.hudMode : "auto",
      pendingReturn: Boolean(parsed.pendingReturn),
      lastPath: typeof parsed.lastPath === "string" ? parsed.lastPath : "/",
      note: typeof parsed.note === "string" ? parsed.note : "No central app crossings recorded yet.",
      journal: Array.isArray(parsed.journal)
        ? parsed.journal.filter((entry): entry is string => typeof entry === "string" && entry.trim().length > 0).slice(-10)
        : [],
      identityNotes: Array.isArray(parsed.identityNotes)
        ? parsed.identityNotes.filter((entry): entry is string => typeof entry === "string" && entry.trim().length > 0).slice(-8)
        : [],
      activeIdentityQuestion: typeof parsed.activeIdentityQuestion === "string" ? parsed.activeIdentityQuestion : "",
      lastIdentityReflection: typeof parsed.lastIdentityReflection === "string" ? parsed.lastIdentityReflection : "",
      activeImprovementLayer: typeof parsed.activeImprovementLayer === "string" ? parsed.activeImprovementLayer : "",
      activeImprovementRoom: typeof parsed.activeImprovementRoom === "string" ? parsed.activeImprovementRoom : "",
      activeImprovementNote: typeof parsed.activeImprovementNote === "string" ? parsed.activeImprovementNote : "",
      lastImprovementResult: typeof parsed.lastImprovementResult === "string" ? parsed.lastImprovementResult : "",
      environmentRooms: sanitizeAlpeccaEnvironmentRooms(parsed.environmentRooms),
      lastCuriosityRoom: typeof parsed.lastCuriosityRoom === "string" ? parsed.lastCuriosityRoom : "",
      lastCuriosityNote: typeof parsed.lastCuriosityNote === "string" ? parsed.lastCuriosityNote : "",
      lastClarityNote: typeof parsed.lastClarityNote === "string" ? parsed.lastClarityNote : "",
      pose: sanitizeAlpeccaPose(parsed.pose),
    };
  } catch {
    return {
      entries: 0,
      returns: 0,
      recursiveDepth: 0,
      selfAudits: 0,
      improvementRuns: 0,
      curiositySweeps: 0,
      identityReflections: 0,
      clarityFeedbacks: 0,
      visualCalmMode: true,
      hudMode: "auto",
      pendingReturn: false,
      lastPath: "/",
      note: "No central app crossings recorded yet.",
      journal: [],
      identityNotes: [],
      activeIdentityQuestion: "",
      lastIdentityReflection: "",
      activeImprovementLayer: "",
      activeImprovementRoom: "",
      activeImprovementNote: "",
      lastImprovementResult: "",
      environmentRooms: {},
      lastCuriosityRoom: "",
      lastCuriosityNote: "",
      lastClarityNote: "",
      pose: null,
    };
  }
}

function sanitizeAlpeccaPose(raw: unknown): AlpeccaAppMemory["pose"] {
  if (!raw || typeof raw !== "object") return null;
  const pose = raw as Partial<NonNullable<AlpeccaAppMemory["pose"]>>;
  if (pose.environment !== "void" && pose.environment !== "hq") return null;
  if (typeof pose.roomId !== "string" || !pose.roomId.trim()) return null;
  const x = Number(pose.x);
  const z = Number(pose.z);
  const yaw = Number(pose.yaw);
  const updatedAt = Number(pose.updatedAt);
  if (![x, z, yaw, updatedAt].every(Number.isFinite)) return null;
  return {
    environment: pose.environment,
    roomId: pose.roomId.slice(0, 80),
    x,
    z,
    yaw,
    updatedAt: Math.max(0, updatedAt),
  };
}

function saveAlpeccaAppMemory() {
  try {
    localStorage.setItem(alpeccaAppMemoryStorageKey, JSON.stringify(alpeccaAppMemory));
  } catch {
    // Local storage can be unavailable in strict privacy contexts; the in-memory loop still works.
  }
}

function persistAlpeccaPose() {
  if (!alpecca.ready && !alpecca.group.parent) return;
  const room = officeRooms.find((item) => roomContains(item, alpecca.group.position.x, alpecca.group.position.z));
  if (!room) return;
  alpeccaAppMemory.pose = {
    environment: isPrototypeMode() ? "void" : "hq",
    roomId: room.id,
    x: alpecca.group.position.x,
    z: alpecca.group.position.z,
    yaw: alpecca.group.rotation.y,
    updatedAt: Date.now(),
  };
  saveAlpeccaAppMemory();
}

function restoreAlpeccaPose() {
  const pose = alpeccaAppMemory.pose;
  const environment = isPrototypeMode() ? "void" : "hq";
  if (!pose || pose.environment !== environment) return false;
  const room = officeRooms.find((item) => item.id === pose.roomId);
  if (!room || !roomContains(room, pose.x, pose.z)) return false;
  const index = alpeccaExplorePoints.findIndex((point) => point.roomId === room.id);
  if (index >= 0) alpecca.exploreIndex = index;
  alpecca.group.position.set(pose.x, currentAlpeccaExplorePoint().position.y, pose.z);
  alpecca.group.rotation.y = pose.yaw;
  alpecca.groundYaw = pose.yaw;
  return true;
}

function pulseAlpeccaAgiJournal(seconds = 2.8) {
  if (!alpeccaAgiJournal) return;
  alpeccaAgiJournal.pulseTimer = Math.max(alpeccaAgiJournal.pulseTimer, seconds);
}

function rememberAlpeccaJournalEntry(note: string) {
  const trimmed = note.trim().replace(/\s+/g, " ");
  if (!trimmed) return;
  const compact = trimmed.length > 220 ? `${trimmed.slice(0, 217)}...` : trimmed;
  alpeccaAppMemory.journal = [...alpeccaAppMemory.journal, compact].slice(-10);
  alpeccaAppMemory.note = compact;
  saveAlpeccaAppMemory();
  pulseAlpeccaAgiJournal(3.2);
}

function calmVisualMultiplier(active = false) {
  if (!alpeccaAppMemory.visualCalmMode) return 1;
  return active ? 0.92 : 0.52;
}

function calmLightMultiplier(active = false) {
  if (!alpeccaAppMemory.visualCalmMode) return 1;
  return active ? 0.9 : 0.42;
}

function seedAlpeccaClarityFeedback() {
  if (alpeccaAppMemory.clarityFeedbacks > 0) return;
  alpeccaAppMemory.clarityFeedbacks = 1;
  alpeccaAppMemory.visualCalmMode = true;
  alpeccaAppMemory.lastClarityNote =
    "Clarity feedback 1: user said the house felt too cluttered. Keep idle systems quieter, preserve walking lanes, and only brighten relevant devices.";
  alpeccaAppMemory.note = alpeccaAppMemory.lastClarityNote;
  saveAlpeccaAppMemory();
  rememberAlpeccaJournalEntry(alpeccaAppMemory.lastClarityNote);
}

seedAlpeccaClarityFeedback();

function writeAlpeccaSelfTrace(note: string) {
  const trace = alpeccaMemoryTraces.get("self-design");
  if (trace) {
    trace.visits += 1;
    trace.pulseTimer = Math.max(trace.pulseTimer, 4.8);
    trace.note = note;
  }
  pulseAlpeccaRoomDevice("self-design", 2.4);
  pulseAlpeccaRoomDetails("self-design", 2);
  pulseAlpeccaSourceTerminal("self", 2.6, true);
  pulseAlpeccaSourceDashboard("self", 2.4);
  if (alpeccaSelfMirror) alpeccaSelfMirror.pulseTimer = Math.max(alpeccaSelfMirror.pulseTimer, 3.4);
}

function sendAlpeccaRecursiveMemory(text: string, waitForReply = true) {
  if (alpeccaAiStatus !== "live" || alpeccaAiAwaitingReply) return;
  alpeccaLiveAttentionTimer = Math.max(alpeccaLiveAttentionTimer, 1.6);
  void alpeccaBackendFetch(alpeccaUrlWithParams(`${alpeccaAiBaseUrl}/cognition/observe`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source: waitForReply ? "recursive-memory-visible" : "recursive-memory",
      room: currentOfficeRoom().name,
      content: `Recursive self-memory from the house: ${text}`,
      confidence: 0.84,
      novelty: 0.55,
      metadata: {
        visible: waitForReply,
        context: alpeccaContextPrefix(),
      },
    }),
  }).catch(() => undefined);
}

async function recordBackendImprovementEvidence(layer: AlpeccaAgiLayer, point: AlpeccaExplorePoint, result: string, online: boolean) {
  if (alpeccaAiStatus === "offline") return;
  try {
    const proposalResponse = await alpeccaBackendFetch(alpeccaUrlWithParams(`${alpeccaAiBaseUrl}/cognition/proposals`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action: `Improve ${layer.name} through ${point.roomName}`,
        reason: layer.description,
        approval: "ask_first",
        risk: "low",
        status: "testing",
        evidence: `${point.action}. ${online ? "The room/system was online." : "The room/system was offline."}`,
      }),
    });
    if (!proposalResponse.ok) return;
    const proposalData = await proposalResponse.json();
    const proposalId = Number(proposalData?.proposal?.id || 0);
    if (!proposalId) return;
    await alpeccaBackendFetch(alpeccaUrlWithParams(`${alpeccaAiBaseUrl}/cognition/proposals/${proposalId}/evaluations`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        phase: "result",
        metric: "house embodiment improvement",
        evidence: point.action,
        test: `Use the ${point.roomName} station as a grounded ${layer.name} improvement experiment.`,
        outcome: result,
        score: online ? 0.72 : 0.42,
        supports_status: online ? "planned" : "testing",
      }),
    });
  } catch {
    // Gameplay should never stall because the backend evidence bridge is offline.
  }
}

function recordAlpeccaSystemsEntry(systemId: AlpeccaSystemId = "overview") {
  alpeccaAppMemory.entries += 1;
  alpeccaAppMemory.recursiveDepth += 1;
  alpeccaAppMemory.pendingReturn = true;
  alpeccaAppMemory.lastPath = systemId;
  alpeccaAppMemory.note = `Systems entry ${alpeccaAppMemory.entries}: CreatorJD opened ${systemId} inside the Void Prototype. Alpecca should connect that system state to her embodied behavior.`;
  saveAlpeccaAppMemory();
  rememberAlpeccaJournalEntry(alpeccaAppMemory.note);
  writeAlpeccaSelfTrace(alpeccaAppMemory.note);
  showMessage("Opening Alpecca's systems inside the Void Prototype.", 3.2);
  sendAlpeccaRecursiveMemory(alpeccaAppMemory.note, true);
}

function recordAlpeccaSystemsReturn() {
  if (!alpeccaAppMemory.pendingReturn) return;
  alpeccaAppMemory.returns += 1;
  alpeccaAppMemory.recursiveDepth += 1;
  alpeccaAppMemory.pendingReturn = false;
  alpeccaAppMemory.note = `Systems return ${alpeccaAppMemory.returns}: CreatorJD closed ${alpeccaAppMemory.lastPath} and returned to the embodied Void.`;
  saveAlpeccaAppMemory();
  rememberAlpeccaJournalEntry(alpeccaAppMemory.note);
  writeAlpeccaSelfTrace(alpeccaAppMemory.note);
  showMessage("Alpecca noticed you returned to the embodied Void.", 3.2);
  sendAlpeccaRecursiveMemory(alpeccaAppMemory.note, true);
}

function alpeccaUrlWithParams(url: string, extraParams: Record<string, string> = {}) {
  if (!url) return "";
  const parsed = new URL(url, window.location.href);
  for (const name of alpeccaLegacyAuthorizationQueryParams) parsed.searchParams.delete(name);
  for (const [key, value] of Object.entries(extraParams)) {
    if (alpeccaLegacyAuthorizationQueryParams.some((name) => name === key)) continue;
    if (value) parsed.searchParams.set(key, value);
  }
  return parsed.toString();
}

function alpeccaBackendFetch(url: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers);
  // Informational only. The backend must authorize the HttpOnly session cookie,
  // never this public identity header.
  headers.set("X-Alpecca-Identity", alpeccaPublicIdentity);
  return fetch(url, {
    ...init,
    credentials: "include",
    headers,
  }).catch(async (error) => {
    await recoverAlpeccaEndpoint("backend-request-failed", {
      backendStorageKey: alpeccaBackendStorageKey,
      force: true,
    });
    throw error;
  });
}

function alpeccaPushBrowserSupported() {
  return window.isSecureContext
    && "serviceWorker" in navigator
    && "PushManager" in window
    && "Notification" in window;
}

function alpeccaPushBackendIsSameOrigin() {
  if (!alpeccaAiBaseUrl) return false;
  try {
    return new URL(alpeccaAiBaseUrl, window.location.href).origin === window.location.origin;
  } catch {
    return false;
  }
}

function registerAlpeccaServiceWorker() {
  if (!("serviceWorker" in navigator)) return Promise.resolve(null);
  if (!alpeccaServiceWorkerRegistrationPromise) {
    alpeccaServiceWorkerRegistrationPromise = navigator.serviceWorker.register("/sw.js")
      .catch((error) => {
        console.warn("Alpecca service worker registration failed.", error);
        alpeccaServiceWorkerRegistrationPromise = null;
        return null;
      });
  }
  return alpeccaServiceWorkerRegistrationPromise;
}

function requestAlpeccaPushAcknowledgementRetry() {
  if (!alpeccaPushBackendIsSameOrigin() || !("serviceWorker" in navigator)) return;
  const now = Date.now();
  if (now - alpeccaPushAckRetryLastRequestedAt < ALPECCA_PUSH_ACK_RETRY_COOLDOWN_MS) return;
  alpeccaPushAckRetryLastRequestedAt = now;
  const message = { type: ALPECCA_PUSH_ACK_RETRY_MESSAGE_TYPE, version: 1 };
  const controller = navigator.serviceWorker.controller;
  if (controller) {
    controller.postMessage(message);
    return;
  }
  void registerAlpeccaServiceWorker().then((registration) => {
    registration?.active?.postMessage(message);
  });
}

if (document.readyState === "complete") {
  void registerAlpeccaServiceWorker();
} else {
  window.addEventListener("load", () => void registerAlpeccaServiceWorker(), { once: true });
}
window.addEventListener("online", requestAlpeccaPushAcknowledgementRetry);
window.addEventListener("focus", requestAlpeccaPushAcknowledgementRetry);

function alpeccaPushApplicationServerKey(status: Record<string, unknown>) {
  const value = status.application_server_key
    ?? status.vapid_public_key
    ?? status.public_key
    ?? status.applicationServerKey;
  return typeof value === "string"
    && value.length >= 32
    && value.length <= 256
    && /^[A-Za-z0-9_-]+$/.test(value)
    ? value
    : "";
}

function alpeccaPushServerReady(status: Record<string, unknown>) {
  if (status.available === false || status.configured === false || status.ready === false) return false;
  return Boolean(alpeccaPushApplicationServerKey(status));
}

function decodeAlpeccaPushApplicationServerKey(value: string) {
  const padded = value.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - value.length % 4) % 4);
  let decoded = "";
  try {
    decoded = window.atob(padded);
  } catch {
    throw new Error("The push application key is invalid.");
  }
  if (decoded.length !== 65) throw new Error("The push application key is invalid.");
  return Uint8Array.from(decoded, (character) => character.charCodeAt(0));
}

function alpeccaPushSubscriptionUsesKey(
  subscription: PushSubscription,
  applicationServerKey: Uint8Array,
) {
  const existingKey = subscription.options.applicationServerKey;
  if (!existingKey) return false;
  const existingBytes = new Uint8Array(existingKey);
  return existingBytes.length === applicationServerKey.length
    && existingBytes.every((value, index) => value === applicationServerKey[index]);
}

async function fetchAlpeccaPushStatus() {
  if (!alpeccaAiBaseUrl) throw new Error("Live backend URL missing");
  if (!alpeccaPushBackendIsSameOrigin()) {
    throw new Error("Creator alerts require House HQ and the backend on the same origin.");
  }
  const path = "/notifications/push/status";
  const response = await alpeccaBackendFetch(alpeccaUrlWithParams(`${alpeccaAiBaseUrl}${path}`), {
    cache: "no-store",
    signal: AbortSignal.timeout(5000),
  });
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  const payload = await response.json() as Record<string, unknown>;
  return { ...payload, ...systemRecord(payload.push) };
}

async function currentAlpeccaPushSubscription() {
  const registration = await registerAlpeccaServiceWorker();
  if (!registration || !("pushManager" in registration)) return null;
  return registration.pushManager.getSubscription();
}

const ALPECCA_CAPABILITY_LEASE_HEADER = "X-Alpecca-Capability-Lease";
const ALPECCA_CAPABILITY_PURPOSE_HEADER = "X-Alpecca-Capability-Purpose";
const ALPECCA_CAPABILITY_CONNECTION_HEADER = "X-Alpecca-Capability-Connection";

function alpeccaCapabilityLabel(purpose: AlpeccaCapabilityPurpose) {
  if (purpose === "camera_frame") return "Camera";
  if (purpose === "push_to_talk") return "Microphone";
  if (purpose === "screen_share") return "Screen sharing";
  if (purpose === "voice_enrollment") return "Voice enrollment";
  return "File attachment";
}

function stopAlpeccaLocalCapabilityMedia() {
  void cancelAlpeccaPushToTalk(false);
  void closeAlpeccaCamera(false);
  void stopAlpeccaScreenShare({ notifyBackend: false, stopLease: false, notice: false });
  void cancelAlpeccaVoiceEnrollment(false);
}

function setAlpeccaCapabilityConnection(value: AlpeccaAiMessage["capability_connection"]) {
  const next = value
    && typeof value.id === "string"
    && value.id.trim()
    && value.surface === "house-hq"
    && value.principal === "creator"
    ? { id: value.id.trim(), surface: "house-hq" as const, principal: "creator" as const }
    : null;
  if (!next) {
    if (alpeccaCapabilityConnection) stopAlpeccaLocalCapabilityMedia();
    clearAlpeccaCapabilityLeases();
    alpeccaCapabilityConnection = null;
    return;
  }
  if (alpeccaCapabilityConnection && alpeccaCapabilityConnection.id !== next.id) {
    stopAlpeccaLocalCapabilityMedia();
    clearAlpeccaCapabilityLeases();
  }
  alpeccaCapabilityConnection = next;
}

function clearAlpeccaCapabilityLeases() {
  alpeccaCapabilityChannelRequest?.abort();
  alpeccaCapabilityChannelRequest = null;
  for (const lease of alpeccaCapabilityLeases.values()) {
    if (lease.expiryTimer !== null) window.clearTimeout(lease.expiryTimer);
    lease.expiryTimer = null;
    lease.token = "";
    lease.stopped = true;
  }
  alpeccaCapabilityLeases.clear();
  if (alpeccaAiPendingCapabilityLease) {
    alpeccaAiPendingCapabilityLease.lease.token = "";
    alpeccaAiPendingCapabilityLease.lease.stopped = true;
  }
  alpeccaAiPendingCapabilityLease = null;
}

async function stopAlpeccaCapabilityLease(
  leaseOrPurpose: AlpeccaCapabilityLease | AlpeccaCapabilityPurpose,
) {
  const lease = typeof leaseOrPurpose === "string"
    ? alpeccaCapabilityLeases.get(leaseOrPurpose)
    : leaseOrPurpose;
  if (!lease || lease.stopped) return;
  lease.stopped = true;
  if (alpeccaCapabilityLeases.get(lease.purpose) === lease) {
    alpeccaCapabilityLeases.delete(lease.purpose);
  }
  if (alpeccaAiPendingCapabilityLease?.lease === lease) alpeccaAiPendingCapabilityLease = null;
  if (lease.expiryTimer !== null) window.clearTimeout(lease.expiryTimer);
  lease.expiryTimer = null;
  const leaseId = lease.leaseId;
  const connectionId = lease.connectionId;
  lease.token = "";
  if (!alpeccaAiBaseUrl || !leaseId || !connectionId) return;
  try {
    await alpeccaBackendFetch(
      alpeccaUrlWithParams(`${alpeccaAiBaseUrl}/security/capability-leases/${encodeURIComponent(leaseId)}/stop`),
      {
        method: "POST",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ connection_id: connectionId }),
      },
    );
  } catch {
    // Disconnect revocation and server expiry remain authoritative if this best-effort stop cannot arrive.
  }
}

function expireAlpeccaCapabilityLease(lease: AlpeccaCapabilityLease) {
  if (alpeccaCapabilityLeases.get(lease.purpose) !== lease) return;
  void stopAlpeccaCapabilityLease(lease);
  if (lease.purpose === "camera_frame") void closeAlpeccaCamera(false);
  else if (lease.purpose === "push_to_talk") void cancelAlpeccaPushToTalk(false);
  else if (lease.purpose === "screen_share") {
    void stopAlpeccaScreenShare({ notifyBackend: true, stopLease: false, notice: true });
  } else if (lease.purpose === "voice_enrollment") void cancelAlpeccaVoiceEnrollment(false);
  else alpeccaCapabilityChannelRequest?.abort();
}

function alpeccaCapabilityLeaseIsUsable(
  lease: AlpeccaCapabilityLease | null | undefined,
  purpose: AlpeccaCapabilityPurpose,
): lease is AlpeccaCapabilityLease {
  if (
    !lease
    || lease.stopped
    || !lease.token
    || lease.purpose !== purpose
    || alpeccaCapabilityLeases.get(purpose) !== lease
    || alpeccaCapabilityConnection?.id !== lease.connectionId
  ) return false;
  if (lease.expiresAt * 1000 <= Date.now()) {
    expireAlpeccaCapabilityLease(lease);
    return false;
  }
  return true;
}

function alpeccaCapabilityLeaseHeaders(lease: AlpeccaCapabilityLease, initial?: HeadersInit) {
  const purpose = lease.purpose;
  if (!alpeccaCapabilityLeaseIsUsable(lease, purpose)) {
    throw new Error(`${alpeccaCapabilityLabel(purpose)} permission expired.`);
  }
  const headers = new Headers(initial);
  headers.set(ALPECCA_CAPABILITY_LEASE_HEADER, lease.token);
  headers.set(ALPECCA_CAPABILITY_PURPOSE_HEADER, lease.purpose);
  headers.set(ALPECCA_CAPABILITY_CONNECTION_HEADER, lease.connectionId);
  return headers;
}

async function acquireAlpeccaCapabilityLease(
  purpose: AlpeccaCapabilityPurpose,
  sourceRef: AlpeccaSourceRef | null = null,
) {
  const connection = alpeccaCapabilityConnection;
  if (
    !connection
    || alpeccaSocket?.readyState !== WebSocket.OPEN
    || !alpeccaAiBaseUrl
  ) {
    throw new Error(`Live House connection is not ready for ${alpeccaCapabilityLabel(purpose).toLowerCase()}.`);
  }
  const conflicts: AlpeccaCapabilityPurpose[] = purpose === "push_to_talk" || purpose === "voice_enrollment"
    ? ["push_to_talk", "voice_enrollment"]
    : [purpose];
  for (const conflict of conflicts) await stopAlpeccaCapabilityLease(conflict);

  const response = await alpeccaBackendFetch(
    alpeccaUrlWithParams(`${alpeccaAiBaseUrl}/security/capability-leases`),
    {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        connection_id: connection.id,
        purpose,
        ...(purpose === "file_source_ref" && sourceRef
          ? { source_ref: { root: sourceRef.root, rel: sourceRef.rel } }
          : {}),
      }),
    },
  );
  if (!response.ok) {
    let reason = "";
    try {
      const payload = await response.json() as { detail?: { reason?: unknown } };
      reason = typeof payload.detail?.reason === "string" ? payload.detail.reason : "";
    } catch {}
    if (reason === "capability_disabled") {
      throw new Error(`${alpeccaCapabilityLabel(purpose)} is not enabled.`);
    }
    throw new Error(`${alpeccaCapabilityLabel(purpose)} permission was not granted.`);
  }
  const payload = await response.json() as Record<string, unknown>;
  const leaseId = typeof payload.lease_id === "string" ? payload.lease_id : "";
  let token = typeof payload.token === "string" ? payload.token : "";
  const expiresAt = typeof payload.expires_at === "number" ? payload.expires_at : Number.NaN;
  if (
    !leaseId
    || !token
    || !Number.isFinite(expiresAt)
    || expiresAt * 1000 <= Date.now()
  ) {
    if (leaseId) {
      await stopAlpeccaCapabilityLease({
        leaseId,
        token: "",
        purpose,
        connectionId: connection.id,
        expiresAt: Number.isFinite(expiresAt) ? expiresAt : 0,
        expiryTimer: null,
        stopped: false,
      });
    }
    token = "";
    throw new Error(`${alpeccaCapabilityLabel(purpose)} permission response was invalid.`);
  }
  const lease: AlpeccaCapabilityLease = {
    leaseId,
    token,
    purpose,
    connectionId: connection.id,
    expiresAt,
    expiryTimer: null,
    stopped: false,
  };
  if (alpeccaCapabilityConnection?.id !== connection.id || alpeccaSocket?.readyState !== WebSocket.OPEN) {
    await stopAlpeccaCapabilityLease(lease);
    throw new Error("Live House connection changed before permission was ready.");
  }
  alpeccaCapabilityLeases.set(purpose, lease);
  const expiresInMs = Math.max(0, Math.min(2_147_000_000, expiresAt * 1000 - Date.now()));
  lease.expiryTimer = window.setTimeout(() => expireAlpeccaCapabilityLease(lease), expiresInMs);
  return lease;
}

function releaseAlpeccaPendingCapabilityLease(requestId = "") {
  const pending = alpeccaAiPendingCapabilityLease;
  if (!pending || (requestId && pending.requestId !== requestId)) return;
  alpeccaAiPendingCapabilityLease = null;
  void stopAlpeccaCapabilityLease(pending.lease);
}

function rememberCompletedAlpeccaRequest(requestId: string) {
  if (!requestId) return;
  alpeccaAiCompletedRequestIds.add(requestId);
  while (alpeccaAiCompletedRequestIds.size > ALPECCA_AI_COMPLETED_REQUEST_LIMIT) {
    const oldest = alpeccaAiCompletedRequestIds.values().next().value;
    if (!oldest) break;
    alpeccaAiCompletedRequestIds.delete(oldest);
  }
}

const alpeccaSystemEndpoints: Record<AlpeccaSystemId, string> = {
  overview: "/home/state",
  internals: "/system/status",
  self: "/introspect",
  devices: "/auth/status",
  senses: "/sight",
  voice: "/voice",
  studio: "/character",
  observatory: "/observatory",
  memory: "/memories",
  journal: "/journal",
  soul: "/soul",
  growth: "/growth",
  files: "/desktop",
  games: "/games",
  mindscape: "/mindscape/state",
  runtime: "/system/status",
};

const alpeccaSystemLabels: Record<AlpeccaSystemId, string> = {
  overview: "Overview",
  internals: "Internals",
  self: "Self",
  devices: "Devices",
  senses: "Senses",
  voice: "Voice",
  studio: "Studio",
  observatory: "Observatory",
  memory: "Memory",
  journal: "Journal",
  soul: "Soul",
  growth: "Growth",
  files: "Files",
  games: "Games",
  mindscape: "Mindscape",
  runtime: "Runtime",
};

function alpeccaSystemFromPath(path: string): AlpeccaSystemId {
  const normalized = String(path || "").toLowerCase().split("?")[0];
  if (normalized.includes("architecture") || normalized.includes("internal")) return "internals";
  if (normalized.includes("observatory")) return "observatory";
  if (normalized.includes("mindscape")) return "mindscape";
  if (normalized.includes("memor")) return "memory";
  if (normalized.includes("journal")) return "journal";
  if (normalized.includes("soul")) return "soul";
  if (normalized.includes("growth") || normalized.includes("workshop")) return "growth";
  if (normalized.includes("desktop") || normalized.includes("file")) return "files";
  if (normalized.includes("game")) return "games";
  if (normalized.includes("voice")) return "voice";
  if (normalized.includes("sight") || normalized.includes("sense")) return "senses";
  if (normalized.includes("studio")) return "studio";
  if (normalized.includes("system") || normalized.includes("doctor")) return "runtime";
  if (normalized.includes("state") || normalized.includes("introspect") || normalized.includes("character")) return "self";
  if (normalized.includes("app") || normalized.includes("device") || normalized.includes("share")) return "devices";
  return "overview";
}

function setAlpeccaSystemsNotice(text: string) {
  alpeccaSystemsNotice.textContent = text;
  alpeccaSystemsNotice.classList.toggle("hidden", !text);
}

function systemString(value: unknown, fallback = "Unavailable") {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return fallback;
}

function systemArray(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => !!item && typeof item === "object")
    : [];
}

function systemIntro(kicker: string, title: string, detail: string) {
  return `<header class="systems-section-head"><span>${escapeHudText(kicker)}</span><div><h2>${escapeHudText(title)}</h2><p>${escapeHudText(detail)}</p></div></header>`;
}

function systemRow(title: string, detail: string, badge = "") {
  return `<div class="systems-row">${badge ? `<span class="systems-badge">${escapeHudText(badge)}</span>` : ""}<div><strong>${escapeHudText(title)}</strong><p>${escapeHudText(detail)}</p></div></div>`;
}

function systemEmpty(text: string) {
  return `<p class="systems-empty">${escapeHudText(text)}</p>`;
}

function systemObjectRows(data: Record<string, unknown>, limit = 16) {
  const ignored = new Set(["recent", "results", "rooms", "games", "slate", "desires", "lessons", "revisions", "proposals", "evaluations"]);
  return Object.entries(data)
    .filter(([key, value]) => !ignored.has(key) && value !== null && value !== undefined)
    .slice(0, limit)
    .map(([key, value]) => {
      const text = typeof value === "object" ? JSON.stringify(value) : String(value);
      return systemRow(key.replace(/_/g, " "), text.slice(0, 320));
    })
    .join("");
}

function systemRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function systemStringArray(value: unknown) {
  return Array.isArray(value)
    ? value.map((item) => systemString(item, "")).filter(Boolean)
    : [];
}

function alpeccaCharacterAssetUrl(kind: "reference" | "image", name: string) {
  if (!alpeccaAiBaseUrl || !name) return "";
  return alpeccaUrlWithParams(`${alpeccaAiBaseUrl}/character/${kind}/${encodeURIComponent(name)}`);
}

// Live visual of how she is steering her own voice right now: engine, mood,
// and animated meters for the modulation she is applying. Refreshes on a timer
// while the Voice system is open (see alpeccaVoiceLivePoll), so it reads as a
// living view rather than a static text dump.
function alpeccaVoiceMeter(label: string, value: number, lo: number, hi: number, hint = ""): string {
  const pct = Math.round(THREE.MathUtils.clamp((value - lo) / Math.max(1e-6, hi - lo), 0, 1) * 100);
  return `<div class="voice-meter"><span>${escapeHudText(label)}<b>${escapeHudText(hint || String(value))}</b></span><i><em style="width:${pct}%"></em></i></div>`;
}

function renderAlpeccaVoiceViewer(data: Record<string, unknown>): string {
  const num = (k: string, d = 0) => (typeof data[k] === "number" && Number.isFinite(data[k] as number) ? (data[k] as number) : d);
  const str = (k: string, d: string) => systemString(data[k], d);
  const engine = str("active_engine", str("last_engine", "warming"));
  const profile = str("profile", "af_heart");
  const primary = str("primary", alpeccaAiMood || "content");
  const tone = str("tone", "even");
  const rate = Math.round(num("rate_pct", Math.round(num("speed", 1) * 100)));
  const semis = num("pitch_semitones", 0);
  return `${systemIntro("VOICE", `${primary} - ${tone} tone`, "How she is shaping her own voice right now, live from her emotional state. This viewer reads her modulation; it does not choose it.")}
    <div class="systems-metrics">
      <div><span>Engine</span><strong>${escapeHudText(engine)}</strong></div>
      <div><span>Profile</span><strong>${escapeHudText(profile)}</strong></div>
      <div><span>Pace</span><strong>${rate}%${semis ? ` / ${semis > 0 ? "+" : ""}${semis} st` : ""}</strong></div>
      <div><span>Session</span><strong>${escapeHudText(alpeccaVoiceSessionState)}</strong></div>
    </div>
    <section><h3>Voice modulation (live)</h3>
      <div class="voice-meters">
        ${alpeccaVoiceMeter("Pitch", num("pitch", 1), 0.88, 1.12, num("pitch", 1).toFixed(3))}
        ${alpeccaVoiceMeter("Speed", num("speed", 1), 0.62, 1.24, num("speed", 1).toFixed(3))}
        ${alpeccaVoiceMeter("Volume", num("volume", 0.8), 0.5, 1.12, num("volume", 0.8).toFixed(3))}
        ${alpeccaVoiceMeter("Warmth", num("warmth", 0.5), 0, 1)}
        ${alpeccaVoiceMeter("Breath", num("breath", 0.25), 0, 1)}
      </div>
      <div class="voice-meters">
        ${alpeccaVoiceMeter("Arousal", num("arousal", 0.5), 0, 1)}
        ${alpeccaVoiceMeter("Valence", num("valence", 0.5), 0, 1)}
        ${alpeccaVoiceMeter("Intensity", num("intensity", 0.5), 0, 1)}
      </div>
    </section>
    <div class="systems-actions"><button type="button" data-system-action="voice-preview">Hear current voice</button></div>`;
}

function renderAlpeccaSystem(systemId: AlpeccaSystemId, data: Record<string, unknown>) {
  if (systemId === "internals") return renderInternalsMap(data as InternalsSnapshot);
  if (systemId === "overview") {
    const home = (data.home || data) as Record<string, unknown>;
    const state = (data.state || {}) as Record<string, unknown>;
    const runtime = (data.runtime || {}) as Record<string, unknown>;
    const runtimeModels = systemRecord(runtime.models);
    const location = systemString(home.location || home.current_room || home.room, "the Void Prototype");
    const mood = systemString(state.mood || (state.state as Record<string, unknown> | undefined)?.mood, alpeccaAiMood || "offline");
    const why = systemString(home.why || home.reason, "No location reason is available.");
    const pulls = home.pulls && typeof home.pulls === "object"
      ? Object.entries(home.pulls as Record<string, unknown>)
          .filter((entry): entry is [string, number] => typeof entry[1] === "number" && Number.isFinite(entry[1]))
          .sort((left, right) => right[1] - left[1])
          .slice(0, 4)
      : [];
    return `${systemIntro("HOME", "One embodied Alpecca", "Her rooms, live affect, runtime, and internal systems now share this one surface.")}
      <div class="systems-metrics">
        <div><span>Location</span><strong>${escapeHudText(location)}</strong></div>
        <div><span>Mood</span><strong>${escapeHudText(mood)}</strong></div>
        <div><span>Model</span><strong>${escapeHudText(systemString(runtimeModels.reason || runtime.model || runtime.ollama_model, "offline"))}</strong></div>
        <div><span>Connection</span><strong>${alpeccaAiStatus === "live" ? "Live" : "Degraded"}</strong></div>
      </div>
      <div class="systems-actions"><button type="button" data-system-id="self">Open self state</button><button type="button" data-system-id="runtime">Open runtime</button><button type="button" data-system-id="growth">Open growth</button></div>
      <section><h3>Home state</h3>${systemRow("Why she is here", why)}${pulls.map(([room, pull]) => systemRow(room, `${Math.round(THREE.MathUtils.clamp(pull, 0, 1) * 100)}% room pull`, "CALL")).join("")}</section>`;
  }
  if (systemId === "self") {
    const mood = systemString(data.mood || (data.state as Record<string, unknown> | undefined)?.mood, alpeccaAiMood || "unknown");
    const narration = systemString(data.narration || data.reason || data.summary, "No grounded self-report is available yet.");
    return `${systemIntro("SELF", `Current mood: ${mood}`, narration)}<section><h3>Grounded internal state</h3>${systemObjectRows(data, 18)}</section>`;
  }
  if (systemId === "devices") {
    const authorization = systemRecord(data.auth || data);
    const trusted = systemRecord(authorization.trusted_device);
    const push = systemRecord(data.push);
    const pushSupported = alpeccaPushBrowserSupported();
    const pushReady = alpeccaPushServerReady(push);
    const pushSubscriptionPresent = push.browser_subscription_present === true;
    const pushSubscribed = push.browser_subscribed === true;
    const pushSubscriptionStale = pushSubscriptionPresent && !pushSubscribed;
    const pushOutbox = systemRecord(push.outbox);
    const pushStates = systemRecord(pushOutbox.states);
    const unresolvedPush = ["queued", "leased", "indeterminate", "sent"]
      .reduce((total, state) => total + Math.max(0, Number(pushStates[state]) || 0), 0);
    const acknowledgedPush = Math.max(0, Number(pushStates.acknowledged) || 0);
    const pushPermission = pushSupported ? Notification.permission : "unsupported";
    const pushPermissionLabel = pushPermission === "granted"
      ? "Granted"
      : pushPermission === "denied"
        ? "Blocked"
        : pushPermission === "default"
          ? "Not requested"
          : "Unsupported";
    const canEnablePush = pushSupported && pushReady && !pushSubscribed && pushPermission !== "denied";
    const canTestPush = pushSupported && pushReady && pushSubscribed && pushPermission === "granted";
    const pushDetail = !pushSupported
      ? "This browser cannot receive Web Push alerts."
      : !pushReady
        ? systemString(push.reason || push.status, "The notification transport is unavailable.")
        : pushSubscriptionStale
          ? "This browser subscription uses an old application key and must be replaced."
          : pushSubscribed
          ? "This browser is registered for creator alerts."
          : "Creator alerts are available but disabled in this browser.";
    return `${systemIntro("DEVICE", "Trusted access", "The current laptop enrolls locally. Other devices validate once, then use an HttpOnly trusted-device session.")}
      <div class="systems-metrics"><div><span>Trust duration</span><strong>${escapeHudText(systemString(trusted.days, "bounded"))} days</strong></div><div><span>Browser secret</span><strong>${trusted.cookie_http_only ? "HttpOnly" : "Unavailable"}</strong></div><div><span>Creator alerts</span><strong>${pushSubscribed ? "Enabled" : "Disabled"}</strong></div><div><span>Permission</span><strong>${pushPermissionLabel}</strong></div></div>
      <div class="systems-actions"><button type="button" data-system-action="device-page">Device setup</button><button type="button" data-system-action="classic-chat">Classic chat</button><button type="button" data-system-action="push-enable"${canEnablePush ? "" : " disabled"}>Enable alerts</button><button type="button" data-system-action="push-disable"${pushSubscriptionPresent ? "" : " disabled"}>Disable alerts</button><button type="button" data-system-action="push-test"${canTestPush ? "" : " disabled"}>Send test</button></div>
      <section><h3>Creator alerts</h3>${systemRow("Web Push", pushDetail, pushSubscribed ? "ON" : pushReady ? "READY" : "OFF")}${systemRow("Outbox", `${acknowledgedPush} acknowledged; ${unresolvedPush} unresolved`, unresolvedPush > 0 ? "PENDING" : "CLEAR")}</section>
      <section><h3>Authorization state</h3>${systemObjectRows(authorization, 12)}</section>`;
  }
  if (systemId === "senses") {
    const flags: Array<[string, unknown, string]> = [
      ["Screen sight", data.screen_active, "Short descriptions only; pixels are not retained."],
      ["Voice tone", data.voice_active, "Local microphone sensing when enabled."],
      ["Webcam", data.face_active, "Local expression sense when enabled."],
      ["Computer use", data.computer_use, "Bounded virtual-environment control."],
    ];
    return `${systemIntro("SENSE", "Perception", systemString(data.screen, "No recent screen description."))}
      <section><h3>Live channels</h3>${flags.map(([name, active, detail]) => systemRow(name, detail, active ? "ON" : "OFF")).join("")}</section>
      <div class="systems-actions"><button type="button" data-system-action="screen-start">Share screen</button><button type="button" data-system-action="screen-stop">Stop sharing</button><button type="button" data-system-action="enroll-voice">Teach creator voice</button></div>`;
  }
  if (systemId === "voice") {
    return renderAlpeccaVoiceViewer(data);
  }
  if (systemId === "mindscape") {
    const status = systemString(data.status || data.sync_status, "local only");
    const cloud = data.cloud_configured === true || data.cloud_url ? "configured" : "local only";
    return `${systemIntro("MINDSCAPE", "Continuity layer", "Her local continuity snapshot. A cloud target is optional and keeps continuity if this device goes down.")}
      <div class="systems-metrics"><div><span>Status</span><strong>${escapeHudText(status)}</strong></div><div><span>Cloud</span><strong>${escapeHudText(cloud)}</strong></div></div>
      <section><h3>Continuity state</h3>${systemObjectRows(data, 20)}</section>`;
  }
  if (systemId === "studio") {
    const sheet = systemRecord(data.sheet);
    const gallery = systemArray(data.gallery);
    const references = systemStringArray(data.reference);
    const rigSpec = systemString(data.rig_spec, "");
    const features = systemStringArray(sheet.features);
    const exclusions = systemStringArray(sheet.never);
    const expressions = systemRecord(sheet.expressions);
    const sheetRows: Array<[string, unknown]> = [
      ["Form", sheet.form],
      ["Style", sheet.style],
      ["Palette story", sheet.palette_story],
    ];
    const referenceFigures = references.map((name) => {
      const imageUrl = alpeccaCharacterAssetUrl("reference", name);
      return `<figure class="systems-media"><img src="${escapeHudText(imageUrl)}" alt="${escapeHudText(`Canonical reference ${name}`)}" loading="lazy"><figcaption>${escapeHudText(name)}</figcaption></figure>`;
    }).join("");
    const galleryFigures = gallery.map((item) => {
      const name = systemString(item.file, "");
      if (!name) return "";
      const imageUrl = alpeccaCharacterAssetUrl("image", name);
      const verdict = systemString(item.verdict, "Kept design");
      return `<figure class="systems-media"><img src="${escapeHudText(imageUrl)}" alt="${escapeHudText(`Kept design ${name}`)}" loading="lazy"><figcaption><strong>${escapeHudText(name)}</strong><span>${escapeHudText(verdict)}</span></figcaption></figure>`;
    }).join("");
    return `${systemIntro("STUDIO", "Character studio", "View Alpecca's actual character sheet, canonical references, kept gallery, and rig specification.")}
      <div class="systems-metrics">
        <div><span>Sheet version</span><strong>${escapeHudText(systemString(sheet.version, "Not authored"))}</strong></div>
        <div><span>References</span><strong>${references.length}</strong></div>
        <div><span>Kept designs</span><strong>${gallery.length}</strong></div>
        <div><span>Rig spec</span><strong>${rigSpec ? "Available" : "Not authored"}</strong></div>
      </div>
      <div class="systems-actions"><button type="button" data-system-action="studio-work">Start one bounded work unit</button></div>
      <section><h3>Current character sheet</h3>${sheetRows.map(([title, value]) => {
        const detail = systemString(value, "");
        return detail ? systemRow(title, detail) : "";
      }).join("") || systemEmpty("No character sheet has been authored yet.")}
        ${features.map((feature) => systemRow("Feature", feature, "SHEET")).join("")}
        ${Object.entries(expressions).map(([mood, expression]) => systemRow(mood, systemString(expression), "EXPR")).join("")}
        ${exclusions.map((item) => systemRow("Never", item, "LOCK")).join("")}
      </section>
      <section><h3>Canonical reference sheets</h3><div class="systems-media-grid">${referenceFigures || systemEmpty("No canonical reference images are available.")}</div></section>
      <section><h3>Kept gallery</h3><div class="systems-media-grid">${galleryFigures || systemEmpty("No kept studio designs yet.")}</div></section>
      <section><h3>Rig specification</h3>${rigSpec ? `<pre class="systems-rig-spec">${escapeHudText(rigSpec)}</pre>` : systemEmpty("No rig specification has been authored yet.")}</section>`;
  }
  if (systemId === "observatory") {
    const watching = (data.watching || {}) as Record<string, unknown>;
    return `${systemIntro("WATCH", "Observatory", "Watch a specific source together and ask for a reaction grounded in her live state.")}
      <div class="systems-input-row"><input id="alpeccaWatchUrl" type="url" placeholder="https:// video or page" aria-label="Watch URL"><button type="button" data-system-action="watch">Watch</button></div>
      <div class="systems-actions"><button type="button" data-system-action="watch-react">What do you think?</button><button type="button" data-system-action="screen-start">Share my screen</button></div>
      <section><h3>Now watching</h3>${Object.keys(watching).length ? systemObjectRows(watching, 10) : systemEmpty("Nothing is playing.")}</section>`;
  }
  if (systemId === "memory") {
    const recent = systemArray(data.recent);
    return `${systemIntro("MEMORY", `${systemString(data.count, "0")} stored memories`, "Recent records and scored search use the same bounded recall path as conversation.")}
      <div class="systems-input-row"><input id="alpeccaMemoryQuery" placeholder="Search memory" aria-label="Search Alpecca memory"><button type="button" data-system-action="memory-search">Search</button></div>
      <div id="alpeccaSystemResults"></div><section><h3>Recent memory</h3>${recent.slice(0, 18).map((item) => systemRow(systemString(item.kind, "memory"), systemString(item.content || item.body))).join("") || systemEmpty("No memories stored yet.")}</section>`;
  }
  if (systemId === "journal") {
    const questions = systemArray(data.open_questions);
    const recent = systemArray(data.recent);
    return `${systemIntro("JOURNAL", "Her notebook", "Questions, dreams, and reflections Alpecca writes through her own bounded processes.")}
      <section><h3>Open questions</h3>${questions.slice(0, 8).map((item) => systemRow("Question", systemString(item.question || item.body || item.content))).join("") || systemEmpty("No open question.")}</section>
      <section><h3>Recent entries</h3>${recent.slice(0, 18).map((item) => systemRow(systemString(item.kind, "entry"), systemString(item.body || item.content), systemString(item.mood, ""))).join("") || systemEmpty("Her notebook is empty.")}</section>`;
  }
  if (systemId === "soul") {
    const focus = (data.focus || {}) as Record<string, unknown>;
    const slate = systemArray(data.slate);
    return `${systemIntro("SOUL", systemString(focus.action || focus.name, "No focus selected"), systemString(focus.reason, "Seven bounded subagents feed one explainable focus."))}
      <section><h3>Seven-subagent slate</h3>${slate.slice(0, 10).map((item) => systemRow(systemString(item.subagent, "subagent"), `${systemString(item.action)} - ${systemString(item.reason)}`, systemString(item.category, ""))).join("") || systemEmpty("No current intentions.")}</section>`;
  }
  if (systemId === "growth") {
    const desires = systemArray(data.desires);
    const lessons = systemArray(data.lessons);
    const proposals = systemArray(data.proposals);
    const commitments = systemArray(data.commitments);
    return `${systemIntro("GROWTH", "Bounded self-improvement", "Evidence-backed proposals remain visible and require the policy-defined creator decision.")}
      <div class="systems-actions"><button type="button" data-system-action="open-workshop">Open approval queue</button><button type="button" data-system-action="run-review">Run self-review</button><button type="button" data-system-action="propose-status">Propose read-only status check</button></div>
      <section><h3>Action commitments</h3>${commitments.slice(0, 12).map((item) => {
        const state = systemString(item.state, "unknown");
        const id = Number(item.id || 0);
        const payload = (item.payload || {}) as Record<string, unknown>;
        const controls = state === "proposed"
          ? `<button type="button" data-commitment-action="approve" data-commitment-id="${id}">Approve</button>`
          : state === "approved"
            ? `<button type="button" data-commitment-action="execute" data-commitment-id="${id}">Execute</button>`
            : "";
        return `<div class="systems-row systems-commitment"><span class="systems-badge">${escapeHudText(state)}</span><div><strong>${escapeHudText(systemString(item.action, "Commitment"))}</strong><p>${escapeHudText(systemString(payload.tool, "text-only; not executable"))}</p></div>${controls ? `<div>${controls}</div>` : ""}</div>`;
      }).join("") || systemEmpty("No action commitments. Text-only promises cannot execute.")}</section>
      <section><h3>Active wants</h3>${desires.slice(0, 8).map((item) => systemRow(systemString(item.kind, "want"), systemString(item.text))).join("") || systemEmpty("No active wants.")}</section>
      <section><h3>Evidence and proposals</h3>${[...lessons, ...proposals].slice(0, 12).map((item) => systemRow(systemString(item.status || item.kind, "evidence"), systemString(item.text || item.action || item.evidence))).join("") || systemEmpty("No current proposal evidence.")}</section>`;
  }
  if (systemId === "files") {
    const sourceActive = alpeccaDriveMode === "source-workspace";
    return `${systemIntro("FILES", "Alpecca Drive", sourceActive ? "Approved source workspace" : "Sandboxed virtual workstation")}
      <div class="systems-actions alpecca-drive-tabs" role="tablist" aria-label="Drive view">
        <button type="button" role="tab" data-drive-mode="virtual-drive" aria-selected="${String(!sourceActive)}"${sourceActive ? "" : " class=\"active\""}>Virtual drive</button>
        <button type="button" role="tab" data-drive-mode="source-workspace" aria-selected="${String(sourceActive)}"${sourceActive ? " class=\"active\"" : ""}>Source workspace</button>
      </div>
      <div id="alpeccaDriveMount" class="alpecca-drive-mount"></div>`;
  }
  if (systemId === "games") {
    const games = systemArray(data.games);
    return `${systemIntro("PLAY", "Games", "Open a safe browser game directly or ask Alpecca's enabled actuator to open it.")}
      <section><h3>Available games</h3>${games.map((item) => {
        const url = systemString(item.url, "");
        const encoded = escapeHudText(encodeURIComponent(url));
        return `<div class="systems-row systems-game"><div><strong>${escapeHudText(systemString(item.name, "Game"))}</strong><p>${escapeHudText(url)}</p></div><div><button type="button" data-game-open="${encoded}">Open</button><button type="button" data-game-alpecca="${encoded}">Ask Alpecca</button></div></div>`;
      }).join("") || systemEmpty("No games configured.")}</section>`;
  }
  return `${systemIntro("RUNTIME", "System health", "Grounded status for the local model, voice, senses, memory, and continuity services.")}
    <div class="systems-actions"><button type="button" data-system-action="doctor">Run doctor</button></div>
    <section><h3>Current services</h3>${systemObjectRows(data, 24) || systemEmpty("Runtime status is unavailable.")}</section>`;
}

async function fetchAlpeccaSystemData(systemId: AlpeccaSystemId) {
  if (!alpeccaAiBaseUrl) throw new Error("Live backend URL missing");
  const fetchJson = async (path: string) => {
    const response = await alpeccaBackendFetch(
      alpeccaUrlWithParams(`${alpeccaAiBaseUrl}${path}`),
      { signal: AbortSignal.timeout(5000) },
    );
    if (!response.ok) throw new Error(`${path} returned ${response.status}`);
    return await response.json() as Record<string, unknown>;
  };
  if (systemId === "overview") {
    const [home, state] = await Promise.all([
      fetchJson("/home/state"),
      fetchJson("/state"),
    ]);
    const runtime = (state.runtime || state.model_use || {}) as Record<string, unknown>;
    return { home, state, runtime };
  }
  if (systemId === "internals") {
    return await fetchJson("/brain/graph");
  }
  if (systemId === "devices") {
    const auth = await fetchJson("/auth/status");
    let push: Record<string, unknown>;
    if (!alpeccaPushBackendIsSameOrigin()) {
      push = {
        available: false,
        reason: "Creator alerts require House HQ and the backend on the same origin.",
      };
    } else {
      try {
        push = await fetchAlpeccaPushStatus();
      } catch (error) {
        push = {
          available: false,
          reason: error instanceof Error ? error.message : "Creator alerts are unavailable.",
        };
      }
    }
    let browserSubscriptionPresent = false;
    let browserSubscribed = false;
    if (alpeccaPushBackendIsSameOrigin()) {
      try {
        const subscription = await currentAlpeccaPushSubscription();
        browserSubscriptionPresent = Boolean(subscription);
        const applicationServerKey = alpeccaPushApplicationServerKey(push);
        browserSubscribed = Boolean(
          subscription
          && applicationServerKey
          && alpeccaPushSubscriptionUsesKey(
            subscription,
            decodeAlpeccaPushApplicationServerKey(applicationServerKey),
          )
        );
      } catch {
        // The server status remains useful when this browser cannot inspect PushManager.
      }
    }
    return {
      auth,
      push: {
        ...push,
        browser_subscription_present: browserSubscriptionPresent,
        browser_subscribed: browserSubscribed,
      },
    };
  }
  return fetchJson(alpeccaSystemEndpoints[systemId]);
}

async function alpeccaDriveRequest(input: RequestInfo | URL, init?: RequestInit) {
  const url = typeof input === "string"
    ? input
    : input instanceof URL
      ? input.toString()
      : input.url;
  const controller = new AbortController();
  const lifecycleSignal = alpeccaDriveRequestController?.signal;
  const inputSignal = init?.signal;
  const forwardAbort = (signal: AbortSignal) => () => controller.abort(signal.reason);
  const lifecycleAbort = lifecycleSignal ? forwardAbort(lifecycleSignal) : null;
  const inputAbort = inputSignal ? forwardAbort(inputSignal) : null;
  if (lifecycleSignal?.aborted) lifecycleAbort?.();
  else lifecycleSignal?.addEventListener("abort", lifecycleAbort!, { once: true });
  if (inputSignal?.aborted) inputAbort?.();
  else inputSignal?.addEventListener("abort", inputAbort!, { once: true });
  const timer = window.setTimeout(() => {
    controller.abort(new DOMException("Drive request timed out.", "TimeoutError"));
  }, ALPECCA_DRIVE_REQUEST_TIMEOUT_MS);
  try {
    const response = await alpeccaBackendFetch(url, { ...init, signal: controller.signal });
    const body = await response.arrayBuffer();
    return new Response(body.byteLength ? body : null, {
      status: response.status,
      statusText: response.statusText,
      headers: response.headers,
    });
  } finally {
    window.clearTimeout(timer);
    if (lifecycleAbort) lifecycleSignal?.removeEventListener("abort", lifecycleAbort);
    if (inputAbort) inputSignal?.removeEventListener("abort", inputAbort);
  }
}

function alpeccaDriveParent(relativePath: string) {
  return relativePath.replace(/\\/g, "/").split("/").filter(Boolean).slice(0, -1).join("/");
}

function alpeccaDriveName(relativePath: string) {
  return relativePath.replace(/\\/g, "/").split("/").filter(Boolean).pop() || relativePath;
}

async function handleAlpeccaDriveIntent(intent: DesktopActionIntent): Promise<DesktopActionReceipt> {
  if (intent.type === "rename") {
    const result = await postAlpeccaSystem("/desktop/rename", {
      root: intent.root,
      rel: intent.rel,
      new_name: intent.newName,
    });
    const parent = alpeccaDriveParent(intent.rel);
    const destination = [parent, intent.newName].filter(Boolean).join("/");
    return {
      action: "rename",
      status: result.ok === true ? "success" : "error",
      message: result.ok === true
        ? `${alpeccaDriveName(intent.rel)} was renamed to ${intent.newName}.`
        : systemString(result.error, "Rename was not confirmed."),
      from: { root: intent.root, rel: intent.rel },
      to: result.ok === true ? { root: intent.root, rel: destination } : undefined,
    };
  }

  const result = await postAlpeccaSystem("/desktop/move", {
    src_root: intent.srcRoot,
    src_rel: intent.srcRel,
    dst_root: intent.dstRoot,
    dst_rel: intent.dstRel,
  });
  const destination = [intent.dstRel, alpeccaDriveName(intent.srcRel)].filter(Boolean).join("/");
  return {
    action: "move",
    status: result.ok === true ? "success" : "error",
    message: result.ok === true
      ? `${alpeccaDriveName(intent.srcRel)} was moved.`
      : systemString(result.error, "Move was not confirmed."),
    from: { root: intent.srcRoot, rel: intent.srcRel },
    to: result.ok === true ? { root: intent.dstRoot, rel: destination } : undefined,
  };
}

function mountAlpeccaDrive() {
  alpeccaDrivePanel?.destroy();
  alpeccaDrivePanel = null;
  alpeccaDriveRequestController?.abort();
  alpeccaDriveRequestController = new AbortController();
  const mount = alpeccaSystemsBody.querySelector<HTMLDivElement>("#alpeccaDriveMount");
  if (!mount || !alpeccaAiBaseUrl) return;
  const sourceMode = alpeccaDriveMode === "source-workspace";
  const dataSource = sourceMode
    ? createSourceWorkspaceHttpDataSource(alpeccaAiBaseUrl, alpeccaDriveRequest)
    : createDesktopHttpDataSource(alpeccaAiBaseUrl, alpeccaDriveRequest);
  alpeccaDrivePanel = createDesktopPanel({
    mode: alpeccaDriveMode,
    dataSource,
    initialLocation: { root: sourceMode ? "source" : "desktop", rel: "" },
    actionsEnabled: !sourceMode,
    onActionIntent: sourceMode ? undefined : handleAlpeccaDriveIntent,
    canAttachFile: (item: DesktopPanelItem) => !item.isDir && isAlpeccaAttachableTextFile(item.rel),
    onAttachFile: (item: DesktopPanelItem) => {
      prepareAlpeccaFileAttachment({ root: item.root, rel: item.rel });
    },
  });
  mount.appendChild(alpeccaDrivePanel.element);
}

async function refreshAlpeccaSystemsAffect() {
  if (!alpeccaAiBaseUrl) return;
  try {
    const response = await alpeccaBackendFetch(
      alpeccaUrlWithParams(`${alpeccaAiBaseUrl}/state`),
      { signal: AbortSignal.timeout(5000) },
    );
    if (!response.ok) return;
    const data = await response.json() as Record<string, unknown>;
    const rawState = data.state;
    if (!rawState || typeof rawState !== "object") return;
    const numericState: Record<string, number> = {};
    for (const [key, value] of Object.entries(rawState)) {
      if (typeof value === "number" && Number.isFinite(value)) numericState[key] = value;
    }
    updateAlpeccaSystemsAffect(numericState, systemString(data.mood, ""));
  } catch {
    // Keep the existing visible state while the backend is unavailable.
  }
}

async function loadAlpeccaSystem(systemId: AlpeccaSystemId = alpeccaActiveSystem) {
  alpeccaActiveSystem = systemId;
  const requestId = ++alpeccaSystemLoadSequence;
  alpeccaDrivePanel?.destroy();
  alpeccaDrivePanel = null;
  alpeccaDriveRequestController?.abort();
  alpeccaDriveRequestController = null;
  alpeccaSystemsNav.querySelectorAll<HTMLButtonElement>("button[data-system-id]").forEach((button) => {
    button.classList.toggle("active", button.dataset.systemId === systemId);
  });
  alpeccaSystemsStatus.textContent = `Loading ${alpeccaSystemLabels[systemId]}...`;
  alpeccaSystemsBody.innerHTML = `<p class="systems-loading">Reading ${escapeHudText(alpeccaSystemLabels[systemId])}...</p>`;
  setAlpeccaSystemsNotice("");
  try {
    const data = await fetchAlpeccaSystemData(systemId);
    if (requestId !== alpeccaSystemLoadSequence) return;
    alpeccaSystemsBody.innerHTML = renderAlpeccaSystem(systemId, data);
    if (systemId === "files") mountAlpeccaDrive();
    if (systemId === "internals") {
      attachInternalsSnapshot(alpeccaSystemsBody, data as unknown as InternalsSnapshot);
      mountInternalsMap(
        alpeccaSystemsBody,
        (targetSystem) => void loadAlpeccaSystem(targetSystem as AlpeccaSystemId),
        () => void loadAlpeccaSystem("internals"),
      );
    }
    const host = alpeccaAiBaseUrl ? new URL(alpeccaAiBaseUrl).host : "offline";
    alpeccaSystemsStatus.textContent = `${alpeccaSystemLabels[systemId]} - live from ${host}`;
    if (systemId === "voice") startAlpeccaVoiceLivePoll();
    else stopAlpeccaVoiceLivePoll();
  } catch (error) {
    if (requestId !== alpeccaSystemLoadSequence) return;
    const message = error instanceof Error ? error.message : "System unavailable";
    alpeccaSystemsBody.innerHTML = systemEmpty("This system could not be read. The embodied Void remains available.");
    alpeccaSystemsStatus.textContent = `${alpeccaSystemLabels[systemId]} unavailable`;
    setAlpeccaSystemsNotice(message);
  }
}

function openAlpeccaSystems(systemId: AlpeccaSystemId = "overview", rememberEntry = true) {
  const wasHidden = alpeccaSystems.classList.contains("hidden");
  if (wasHidden && rememberEntry) recordAlpeccaSystemsEntry(systemId);
  if (document.pointerLockElement === renderer.domElement) document.exitPointerLock();
  collapseHudCards();
  alpeccaSystems.classList.remove("hidden");
  document.body.classList.add("alpecca-systems-open");
  updateAlpeccaSystemsAffect();
  void refreshAlpeccaSystemsAffect();
  void loadAlpeccaSystem(systemId);
}

function closeAlpeccaSystems() {
  void cancelAlpeccaVoiceEnrollment();
  const screenWasActive = Boolean(alpeccaScreenShareStream || alpeccaCapabilityLeases.has("screen_share"));
  void stopAlpeccaScreenShare({ notifyBackend: screenWasActive, stopLease: true, notice: false });
  alpeccaSystems.classList.add("hidden");
  document.body.classList.remove("alpecca-systems-open");
  alpeccaSystemLoadSequence += 1;
  alpeccaDrivePanel?.destroy();
  alpeccaDrivePanel = null;
  alpeccaDriveRequestController?.abort();
  alpeccaDriveRequestController = null;
  stopAlpeccaVoiceLivePoll();
  recordAlpeccaSystemsReturn();
}

function openAlpeccaPage(path: string, rememberEntry = false) {
  openAlpeccaSystems(alpeccaSystemFromPath(path), rememberEntry);
}

function openAlpeccaTerminal(rememberEntry = true) {
  openAlpeccaSystems("overview", rememberEntry);
}

function visibleAlpeccaEmotionState() {
  return alpeccaVoiceEmotionTimer > 0
    ? { ...alpeccaAiState, ...alpeccaVoiceEmotionState }
    : alpeccaAiState;
}

function updateAlpeccaSystemsAffect(
  stateOverride?: Record<string, number>,
  moodOverride = "",
) {
  const state = stateOverride || visibleAlpeccaEmotionState();
  const signals: Array<[string, string]> = [
    ["love", "Love"],
    ["compassion", "Care"],
    ["fear", "Stress"],
    ["energy", "Energy"],
  ];
  alpeccaSystemsAffect.innerHTML = `
    <div class="systems-affect-mood"><span>Emotion</span><strong>${escapeHudText(moodOverride || alpeccaAiMood || "offline")}</strong></div>
    ${signals.map(([key, label]) => {
      const raw = state[key];
      const value = Number.isFinite(raw) ? THREE.MathUtils.clamp(raw, 0, 1) : 0;
      const percent = Math.round(value * 100);
      return `<div class="systems-affect-signal" data-affect="${key}"><span>${label}<b>${percent}%</b></span><i><em style="width:${percent}%"></em></i></div>`;
    }).join("")}`;
}

function updateAlpeccaMoodPanel() {
  alpeccaMoodReadout.textContent = alpeccaAiStatus === "live" ? alpeccaAiMood : alpeccaAiStatus === "token" ? "reconnect" : "offline";
  sourceChipMood.textContent = alpeccaMoodReadout.textContent;
  sourceChip.dataset.status = alpeccaAiStatus;
  const visibleState = visibleAlpeccaEmotionState();
  const keysToShow: Array<[string, string]> = [
    ["love", "Love"],
    ["compassion", "Care"],
    ["fear", "Fear"],
    ["energy", "Energy"],
  ];
  alpeccaMoodBars.innerHTML = keysToShow
    .map(([key, label]) => {
      const raw = visibleState[key];
      const value = Number.isFinite(raw) ? THREE.MathUtils.clamp(raw, 0, 1) : 0;
      return `<div class="mood-row"><span>${label}</span><i style="--value:${Math.round(value * 100)}%"></i></div>`;
    })
    .join("");
  updateAlpeccaSystemsAffect();
}

function sourcePlateForAlpeccaState(state: AlpeccaAnimationName) {
  if (state.startsWith("walk") || state.startsWith("run") || state.startsWith("jump") || state === "dash" || state === "climb") {
    return "movement";
  }
  if (
    state === "point" ||
    state === "pickup" ||
    state === "wave" ||
    state.startsWith("wave") ||
    state === "crouch" ||
    state === "kneel"
  ) {
    return "gestures";
  }
  if (state === "dance" || state === "victory") return "expressions";
  if (state === "sit" || state.startsWith("sleep")) return "wardrobe";
  return "master";
}

function setAlpeccaSourcePlate(id: string) {
  if (currentAlpeccaSourcePlate === id) return;
  const plate = alpeccaSourcePlates[id] ?? alpeccaSourcePlates.master;
  currentAlpeccaSourcePlate = plate.id;
  alpeccaSourceArtLabel.textContent = plate.label;
  alpeccaSourceArtHint.textContent = plate.hint;
  alpeccaSourceArtImage.style.backgroundImage = `image-set(url("${alpeccaSourceArtRoot}/${plate.file}.webp") type("image/webp"), url("${alpeccaSourceArtRoot}/${plate.file}.png") type("image/png"))`;
  pulseAlpeccaSourceGallery(plate.id, 2.2);
}

function setAlpeccaAiStatus(status: AlpeccaAiStatus, mood = alpeccaAiMood) {
  alpeccaAiStatus = status;
  alpeccaAiMood = mood || status;
  const label =
    status === "live"
      ? `${alpeccaAiLlmOnline ? "Live" : "Live Basic"}${mood && mood !== "live" ? ` (${mood})` : ""}`
      : status === "connecting"
        ? "Connecting"
        : status === "token"
          ? "Reconnect"
          : "Offline";
  alpeccaAiStatusEl.textContent = `Alpecca AI: ${label}`;
  alpeccaAiStatusEl.dataset.status = status;
  updateAlpeccaMoodPanel();
  updateCoreStatusLabels();
  if (status === "live" || status === "connecting") {
    for (const terminal of alpeccaSourceTerminals.keys()) pulseAlpeccaSourceTerminal(terminal, status === "live" ? 1.8 : 0.9);
  }
  pulseAlpeccaSourceDashboard("", status === "live" ? 2.6 : 1.4);
  if (status !== "live") setAlpeccaMindpageState(null);
}

function setAlpeccaMindpageState(state: AlpeccaMindpageState | null | undefined) {
  if (!state || state.enabled === false || typeof state.context_fill !== "number") {
    alpeccaMemoryPressureEl.dataset.pressure = "unavailable";
    alpeccaMemoryPressureLabel.textContent = "Unavailable";
    alpeccaMemoryPressureBar.style.width = "0%";
    alpeccaMemoryPressureEl.title = "Working-memory telemetry is unavailable";
    chipLoop.dataset.pressure = "unavailable";
    chipPressureBar.style.width = "0%";
    return;
  }
  const fill = THREE.MathUtils.clamp(state.context_fill, 0, 1);
  const pressure = String(state.pressure || (fill >= 0.9 ? "high" : fill >= 0.75 ? "medium" : "low")).toLowerCase();
  const band = pressure === "high" ? "High" : pressure === "medium" ? "Medium" : "Low";
  const percent = Math.round(fill * 100);
  const pages = Math.max(0, Number(state.page_count || 0));
  const backlog = Math.max(0, Number(state.unsummarized_eviction_backlog || 0));
  alpeccaMemoryPressureEl.dataset.pressure = pressure;
  alpeccaMemoryPressureLabel.textContent = `${band} ${percent}%`;
  alpeccaMemoryPressureBar.style.width = `${percent}%`;
  chipLoop.dataset.pressure = pressure;
  chipPressureBar.style.width = `${percent}%`;
  alpeccaMemoryPressureEl.title = `Measured request pressure: ${percent}%. ${pages} compressed page${pages === 1 ? "" : "s"}; ${backlog} excluded message${backlog === 1 ? "" : "s"}.`;
}

function scheduleAlpeccaAiRetry(delay = 5) {
  alpeccaAiRetryTimer = Math.max(alpeccaAiRetryTimer, delay);
}

async function probeAlpeccaAiServer() {
  if (!alpeccaAiBaseUrl) return false;
  try {
    await alpeccaBackendFetch(alpeccaUrlWithParams(`${alpeccaAiBaseUrl}/state`), {
      cache: "no-store",
    });
    return true;
  } catch {
    return false;
  }
}

function connectAlpeccaAi() {
  if (alpeccaSocket && (alpeccaSocket.readyState === WebSocket.OPEN || alpeccaSocket.readyState === WebSocket.CONNECTING)) return;
  if (alpeccaAiStatus === "connecting") return;
  if (!alpeccaAiBaseUrl || !alpeccaAiWsBaseUrl) {
    setAlpeccaAiStatus("offline", "offline");
    alpeccaAiStatusEl.textContent = "Alpecca AI: Backend URL needed";
    return;
  }
  setAlpeccaAiStatus("connecting");

  if (alpeccaAiProbeTimer !== null) window.clearTimeout(alpeccaAiProbeTimer);
  alpeccaAiProbeTimer = window.setTimeout(async () => {
    alpeccaAiProbeTimer = null;
    const reachable = await probeAlpeccaAiServer();
    alpeccaAiServerReachable = reachable;
    if (!reachable) {
      setAlpeccaAiStatus("offline", "offline");
      if (!alpeccaAiOfflineNoticeShown) {
        showMessage("Live Alpecca is offline. Using local game dialogue.", 4);
        alpeccaAiOfflineNoticeShown = true;
      }
      scheduleAlpeccaAiRetry(5);
      return;
    }

    try {
      alpeccaSocket = new WebSocket(alpeccaUrlWithParams(alpeccaAiWsBaseUrl));
    } catch {
      setAlpeccaAiStatus("offline", "offline");
      scheduleAlpeccaAiRetry(5);
      return;
    }

    let opened = false;
    alpeccaSocket.addEventListener("open", () => {
      opened = true;
      alpeccaAvatarPlaybackSignal.reset("backend connected");
      alpeccaAiOfflineNoticeShown = false;
      setAlpeccaAiStatus("live", alpeccaAiMood === "offline" ? "awake" : alpeccaAiMood);
      showMessage("Live Alpecca AI connected.", 2.8);
      alpeccaPresenceContextTimer = 0.2;
      sendAlpeccaPresenceContext(true);
    });

    alpeccaSocket.addEventListener("message", (event) => {
      handleAlpeccaAiMessage(event.data);
    });

    alpeccaSocket.addEventListener("close", (event) => {
      stopAlpeccaLocalCapabilityMedia();
      clearAlpeccaCapabilityLeases();
      alpeccaCapabilityConnection = null;
      alpeccaSocket = null;
      alpeccaAiAwaitingReply = false;
      alpeccaAiReplyStartedAt = 0;
      alpeccaAiSlowReplyNoticeShown = false;
      alpeccaAiPendingPlayerRequestId = "";
      alpeccaAiLastPlayerMessage = "";
      alpeccaVoiceLastText = "";
      alpeccaVoiceSession.interrupt({ clearQueue: true, reason: "backend disconnected" });
      alpeccaVoiceSession.reset("idle", "backend disconnected");
      alpeccaAvatarPlaybackSignal.reset("backend disconnected");
      setAlpeccaProfileMode("listening", alpeccaActiveProfileFeature);
      if (event.code === 1008 || (!opened && alpeccaAiServerReachable)) {
        setAlpeccaAiStatus("token", "session");
        showMessage("Alpecca needs an authorized backend session. Sign in through the live app, then reconnect.", 5);
      } else {
        setAlpeccaAiStatus("offline", "offline");
        scheduleAlpeccaAiRetry(5);
      }
    });

    alpeccaSocket.addEventListener("error", () => {
      alpeccaSocket?.close();
    });
  }, 150);
}

function normalizeAlpeccaReplyText(text: string, message: AlpeccaAiMessage) {
  const clean = text.trim();
  const echo = clean.match(/^You said:\s*[“"]?([\s\S]*?)[”"]?\.?(\s*\[offline:[\s\S]*?\])?$/i);
  if (!echo) return clean;
  if (message.llm_online) return clean;
  return "I'm here with you. My deeper language core is offline or stalled, so I'm answering from basic live mode instead of just repeating your message.";
}

function handleAlpeccaAiMessage(raw: string) {
  let message: AlpeccaAiMessage;
  try {
    message = JSON.parse(raw) as AlpeccaAiMessage;
  } catch {
    return;
  }
  const responseText = (message.reply || message.text || message.message || message.content || "").trim();

  if (message.type === "state") setAlpeccaCapabilityConnection(message.capability_connection);

  if (typeof message.llm_online === "boolean") alpeccaAiLlmOnline = message.llm_online;
  if (message.model_use) alpeccaAiModelUse = message.model_use;
  else if (message.cognition?.models?.last_call) alpeccaAiModelUse = message.cognition.models.last_call;
  const mindpage = message.mindpage || message.cognition?.mindpage;
  if (mindpage) setAlpeccaMindpageState(mindpage);
  updateCoreStatusLabels();
  if (message.living_loop) setAlpeccaLivingState(message.living_loop, responseText);
  else if (message.cognition?.intent) {
    const intent = message.cognition.intent;
    const intentName = typeof intent.name === "string" ? intent.name : "waiting";
    const target = typeof intent.target === "string" && intent.target ? intent.target : currentOfficeRoom().name;
    const reason = typeof intent.reason === "string" ? intent.reason : "Alpecca is updating her current state.";
    setAlpeccaLivingState(
      { phase: intentName, question: reason, room: { name: target }, intent: { name: intentName, reason, target } },
      reason,
    );
  }
  if (message.mood) setAlpeccaAiStatus("live", message.mood);
  if (message.state) {
    alpeccaAiState = message.state;
    updateAlpeccaMoodPanel();
    pulseAlpeccaSourceDashboard("", 1.4);
    alpeccaVrmEmbodiment?.setMood(alpeccaAiMood, alpeccaEmotionDims());
  }

  if (message.type === "state") {
    return;
  }

  if (message.type === "living_loop") {
    const line = message.living_loop?.line || responseText || "Alpecca asked herself a grounded question.";
    setAlpeccaActivity("Alpecca is recursively questioning her world.", "observe", 4.2);
    setAlpeccaLivingState(message.living_loop, line);
    routeAlpeccaToLivingLoopTarget(message.living_loop);
    pulseAlpeccaActivatedSystem(message.living_loop?.activated_system?.id || "");
    if (!alpeccaChat.classList.contains("hidden")) showAlpeccaProfileLine(line, "thinking", "home");
    else showMessage(line, 5.5);
    alpecca.glitchTimer = Math.max(alpecca.glitchTimer, 0.24);
    alpeccaProfileGlitchTimer = Math.max(alpeccaProfileGlitchTimer, 0.42);
    return;
  }

  if (message.type === "reply") {
    const replyRequestId = message.request_id || "";
    if (replyRequestId && alpeccaAiCompletedRequestIds.has(replyRequestId)) return;
    const fromPlayerChat = Boolean(replyRequestId) && replyRequestId === alpeccaAiPendingPlayerRequestId;
    const legacyPlayerReply =
      alpeccaAiAwaitingReply &&
      !replyRequestId &&
      !message.source &&
      (!alpeccaAiLastPlayerMessage || responseText.toLowerCase().includes(alpeccaAiLastPlayerMessage.toLowerCase()));
    const wasAwaitingPlayerReply = fromPlayerChat || legacyPlayerReply;
    pulseAlpeccaSourceDashboard("", 2.8);
    const replyText = normalizeAlpeccaReplyText(responseText || "Alpecca is here.", message);
    if (!wasAwaitingPlayerReply) {
      const sourceLabel = message.source ? ` from ${message.source}` : "";
      appendAlpeccaLog("System", `Background core event${sourceLabel}.`);
      setAlpeccaActivity("Alpecca filed a background core event.", "observe", 2.2);
      return;
    }
    rememberCompletedAlpeccaRequest(replyRequestId);
    releaseAlpeccaPendingCapabilityLease(replyRequestId);
    alpeccaAiAwaitingReply = false;
    alpeccaAiReplyStartedAt = 0;
    alpeccaAiSlowReplyNoticeShown = false;
    alpeccaAiExtendedReplyNoticeShown = false;
    alpeccaAiPendingPlayerRequestId = "";
    alpeccaAiLastPlayerMessage = "";
    alpeccaPlayerChatQuietTimer = Math.max(alpeccaPlayerChatQuietTimer, 10);
    appendAlpeccaLog("Alpecca", replyText);
    if (message.model_use) {
      const modelLabel = alpeccaModelUseLabel(message.model_use);
      const modelName = message.model_use.model ? ` (${message.model_use.model})` : "";
      appendAlpeccaLog("System", `Core: ${modelLabel}${modelName}`);
    }
    const topMemory = message.memory_evidence?.[0];
    if (topMemory?.content) {
      const score = typeof topMemory.score === "number" ? ` ${topMemory.score.toFixed(2)}` : "";
      appendAlpeccaLog("System", `Memory: ${topMemory.kind || "memory"}${score} / ${topMemory.method || "recall"}`);
    }
    setAlpeccaActivity(wasAwaitingPlayerReply ? "Alpecca is answering through the live core." : "Alpecca sent a live reply.", "think");
    const replyWaveReady = alpecca.animations.has("waveDown");
    focusAlpecca(3.2, "waveDown");
    const spokenReplyText = (message.spoken_reply || message.spoken_text || replyText).trim();
    if (alpeccaSpokenRepliesEnabled) {
      startAlpeccaSpeech(spokenReplyText);
    } else {
      alpeccaVoiceSession.setConversationState("listening", "spoken replies are muted");
    }
    alpecca.glitchTimer = Math.max(alpecca.glitchTimer, 0.3);
    alpeccaProfileGlitchTimer = Math.max(alpeccaProfileGlitchTimer, 0.45);
    alpecca.expressiveTimer = Math.max(alpecca.expressiveTimer, replyWaveReady ? 1.05 : 3.5);
    if (["joyful", "playful", "affectionate"].some((word) => alpeccaAiMood.includes(word))) {
      alpecca.expressiveTimer = 1.45;
      setAlpeccaSpriteFlip(false);
      setAlpeccaAnimation(activatedRooms >= activeRoomTotal() ? "victory" : "waveDown");
    }
    alpeccaChatLine.textContent = replyText;
    showAlpeccaProfileLine(replyText, "listening", alpeccaActiveProfileFeature);
    showMessage(replyText, 7);
    return;
  }

  if (message.type === "error") {
    const requestId = message.request_id || "";
    const matchesPending = !requestId || requestId === alpeccaAiPendingPlayerRequestId;
    if (!matchesPending) return;
    rememberCompletedAlpeccaRequest(requestId);
    releaseAlpeccaPendingCapabilityLease(requestId);
    alpeccaAiAwaitingReply = false;
    alpeccaAiReplyStartedAt = 0;
    alpeccaAiSlowReplyNoticeShown = false;
    alpeccaAiExtendedReplyNoticeShown = false;
    alpeccaAiPendingPlayerRequestId = "";
    alpeccaAiLastPlayerMessage = "";
    const errorText = message.code === "capability_lease_denied"
      ? "Camera permission was rejected or expired."
      : (message.error || message.detail || "Alpecca could not process that attachment.");
    appendAlpeccaLog("System", errorText);
    alpeccaVoiceSession.setConversationState("listening", "reply failed");
    showAlpeccaProfileLine(errorText, "listening");
    showMessage(errorText, 5);
    return;
  }

  if (message.type === "proactive" && responseText) {
    const proactiveText = responseText;
    // The server only emits this after the shared initiative budget accepted a
    // grounded, single delivery. Present it as Alpecca's own spoken initiative,
    // not as an opaque system event.
    appendAlpeccaLog("Alpecca", proactiveText);
    setAlpeccaActivity("Alpecca is speaking from her live state.", "think", 2.4);
    pulseAlpeccaSourceDashboard("", 2.4);
    alpecca.glitchTimer = Math.max(alpecca.glitchTimer, 0.22);
    alpeccaProfileGlitchTimer = Math.max(alpeccaProfileGlitchTimer, 0.34);
    focusAlpecca(2.8, "talkDown");
    alpecca.expressiveTimer = Math.max(alpecca.expressiveTimer, 2.4);
    alpeccaChatLine.textContent = proactiveText;
    showAlpeccaProfileLine(
      proactiveText,
      "listening",
      alpeccaActiveProfileFeature,
    );
    showMessage(proactiveText, 7);
    if (alpeccaSpokenRepliesEnabled) {
      startAlpeccaSpeech(proactiveText, "", "proactive");
    }
    return;
  }

  if (message.type === "computer_status" && message.text) {
    appendAlpeccaLog("System", message.text);
    showMessage(message.text, 4);
    return;
  }

  if (message.type === "computer_done" && (message.summary || message.error)) {
    showMessage(message.summary || message.error || "", 4);
    return;
  }

  if (responseText) {
    appendAlpeccaLog("System", responseText);
    setAlpeccaActivity(`Alpecca event: ${responseText}`, "observe", 2.5);
    return;
  }

  if ((message.error || message.detail) && !responseText) {
    alpeccaAiAwaitingReply = false;
    alpeccaAiReplyStartedAt = 0;
    alpeccaAiSlowReplyNoticeShown = false;
    alpeccaAiPendingPlayerRequestId = "";
    alpeccaAiLastPlayerMessage = "";
    const errorText = message.error || message.detail || "Alpecca could not answer that message.";
    appendAlpeccaLog("System", errorText);
    showAlpeccaProfileLine(errorText, "listening");
    showMessage(errorText, 5);
  }
}

function openAlpeccaChat() {
  chatWasPointerLocked = document.pointerLockElement === renderer.domElement;
  if (chatWasPointerLocked) document.exitPointerLock();
  alpeccaChat.classList.remove("hidden");
  alpeccaChat.scrollTop = 0;
  alpecca.showcaseTimer = 0;
  setAlpeccaProfileMode("listening");
  focusAlpecca(3.5, "idleDown");
  alpecca.expressiveTimer = Math.max(alpecca.expressiveTimer, 0.65);
  const animation = alpecca.animations.get(alpecca.state);
  const frame = animation?.frames[animation.frameIndex];
  const image = animation?.texture.image as HTMLImageElement | undefined;
  if (!updateAlpeccaChatExpressionPortrait(true) && animation && frame && image?.width) {
    updateAlpeccaProfileFrame(animation, frame, image);
  }
  alpeccaChatLine.textContent = `Ask Alpecca about ${currentOfficeRoom().name}, her memory, or the HQ.`;
  alpeccaChatInput.value = "";
  alpeccaChatInput.focus();
}

function closeAlpeccaChat() {
  alpeccaCapabilityChannelRequest?.abort();
  releaseAlpeccaPendingCapabilityLease();
  void stopAlpeccaCapabilityLease("file_source_ref");
  void cancelAlpeccaPushToTalk();
  void closeAlpeccaCamera();
  alpeccaPendingSourceRef = null;
  alpeccaChatInput.placeholder = "Message Alpecca...";
  alpeccaChat.classList.add("hidden");
  alpeccaChatInput.blur();
  renderer.domElement.focus();
}

function updateAlpeccaSpokenRepliesButton() {
  alpeccaSpokenRepliesButton.setAttribute("aria-pressed", String(alpeccaSpokenRepliesEnabled));
  alpeccaSpokenRepliesButton.setAttribute("aria-label", alpeccaSpokenRepliesEnabled ? "Mute spoken replies" : "Enable spoken replies");
  alpeccaSpokenRepliesButton.title = alpeccaSpokenRepliesEnabled ? "Mute spoken replies" : "Enable spoken replies";
}

function toggleAlpeccaSpokenReplies() {
  alpeccaSpokenRepliesEnabled = !alpeccaSpokenRepliesEnabled;
  localStorage.setItem(alpeccaSpokenRepliesStorageKey, alpeccaSpokenRepliesEnabled ? "on" : "off");
  updateAlpeccaSpokenRepliesButton();
  if (!alpeccaSpokenRepliesEnabled) {
    alpeccaVoiceLastText = "";
    alpeccaVoiceSession.interrupt({ clearQueue: true, reason: "spoken replies muted" });
    alpeccaVoiceSession.reset("listening", "spoken replies muted");
    alpeccaAvatarPlaybackSignal.reset("spoken replies muted");
    setAlpeccaProfileMode("listening", alpeccaActiveProfileFeature);
  } else {
    alpeccaVoiceSession.reset("listening", "spoken replies enabled");
  }
  appendAlpeccaLog("System", `Spoken replies ${alpeccaSpokenRepliesEnabled ? "enabled" : "muted"}.`);
}

function setAlpeccaPushToTalkState(state: "idle" | "recording" | "processing") {
  const recording = state === "recording";
  alpeccaPushToTalkButton.dataset.state = state;
  alpeccaPushToTalkButton.disabled = state === "processing";
  alpeccaPushToTalkButton.setAttribute("aria-pressed", String(recording));
  alpeccaPushToTalkButton.setAttribute("aria-label", recording ? "Stop and send voice input" : "Start push-to-talk");
  alpeccaPushToTalkButton.title = recording ? "Stop and send voice input" : state === "processing" ? "Transcribing voice input" : "Start push-to-talk";
  if (state === "recording") alpeccaVoiceSession.setConversationState("listening", "microphone recording");
  else if (state === "processing") alpeccaVoiceSession.setConversationState("thinking", "transcribing microphone input");
  else if (!alpeccaAiAwaitingReply) alpeccaVoiceSession.setConversationState("listening", "ready for voice input");
}

function stopAlpeccaPushToTalkStream() {
  alpeccaPushToTalkStream?.getTracks().forEach((track) => {
    track.onended = null;
    track.stop();
  });
  alpeccaPushToTalkStream = null;
}

function clearAlpeccaPushToTalkStopTimer() {
  if (alpeccaPushToTalkStopTimer === null) return;
  window.clearTimeout(alpeccaPushToTalkStopTimer);
  alpeccaPushToTalkStopTimer = null;
}

async function cancelAlpeccaPushToTalk(stopLease = true) {
  alpeccaPushToTalkSequence += 1;
  clearAlpeccaPushToTalkStopTimer();
  alpeccaPushToTalkRequest?.abort();
  alpeccaPushToTalkRequest = null;
  const recorder = alpeccaPushToTalkRecorder;
  alpeccaPushToTalkRecorder = null;
  alpeccaPushToTalkChunks = [];
  if (recorder) {
    recorder.ondataavailable = null;
    recorder.onstop = null;
    recorder.onerror = null;
    if (recorder.state !== "inactive") recorder.stop();
  }
  stopAlpeccaPushToTalkStream();
  setAlpeccaPushToTalkState("idle");
  if (stopLease) await stopAlpeccaCapabilityLease("push_to_talk");
}

async function transcribeAlpeccaPushToTalk(
  blob: Blob,
  sequence: number,
  lease: AlpeccaCapabilityLease,
) {
  if (sequence !== alpeccaPushToTalkSequence || alpeccaChat.classList.contains("hidden")) {
    await stopAlpeccaCapabilityLease(lease);
    return;
  }
  if (!blob.size || !alpeccaAiBaseUrl) {
    showAlpeccaProfileLine("Voice input needs the live local backend.", "listening");
    setAlpeccaPushToTalkState("idle");
    await stopAlpeccaCapabilityLease(lease);
    return;
  }
  const request = new AbortController();
  alpeccaPushToTalkRequest = request;
  setAlpeccaPushToTalkState("processing");
  showAlpeccaProfileLine("Transcribing your voice locally...", "thinking");
  try {
    const response = await alpeccaBackendFetch(alpeccaUrlWithParams(`${alpeccaAiBaseUrl}/listen`), {
      method: "POST",
      headers: alpeccaCapabilityLeaseHeaders(
        lease,
        blob.type ? { "Content-Type": blob.type } : undefined,
      ),
      body: blob,
      signal: request.signal,
    });
    if (!response.ok) throw new Error(`voice input returned ${response.status}`);
    const data = await response.json() as Record<string, unknown>;
    void stopAlpeccaCapabilityLease(lease);
    if (sequence !== alpeccaPushToTalkSequence || alpeccaChat.classList.contains("hidden")) return;
    const heard = data.heard === true ? systemString(data.text, "") : "";
    if (!heard) {
      showAlpeccaProfileLine("I could not make that out. Try speaking a little closer to the microphone.", "listening");
      return;
    }
    await sendAlpeccaChat(heard, "", "microphone");
  } catch (error) {
    if (sequence !== alpeccaPushToTalkSequence || request.signal.aborted) return;
    const detail = error instanceof Error ? error.message : "voice input failed";
    appendAlpeccaLog("System", detail);
    showAlpeccaProfileLine("Voice transcription is unavailable right now.", "listening");
  } finally {
    if (alpeccaPushToTalkRequest === request) alpeccaPushToTalkRequest = null;
    if (sequence === alpeccaPushToTalkSequence) setAlpeccaPushToTalkState("idle");
    await stopAlpeccaCapabilityLease(lease);
  }
}

async function toggleAlpeccaPushToTalk() {
  const activeRecorder = alpeccaPushToTalkRecorder;
  if (activeRecorder) {
    if (activeRecorder.state === "recording") {
      clearAlpeccaPushToTalkStopTimer();
      activeRecorder.stop();
    }
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
    showAlpeccaProfileLine("This browser does not provide microphone recording.", "listening");
    return;
  }
  await closeAlpeccaCamera();
  await cancelAlpeccaVoiceEnrollment();
  alpeccaVoiceSession.interrupt({ clearQueue: true, reason: "creator started speaking" });
  if (alpeccaChat.classList.contains("hidden")) return;
  const sequence = ++alpeccaPushToTalkSequence;
  let lease: AlpeccaCapabilityLease | null = null;
  try {
    lease = await acquireAlpeccaCapabilityLease("push_to_talk");
    const recorderLease = lease;
    if (sequence !== alpeccaPushToTalkSequence || alpeccaChat.classList.contains("hidden")) {
      await stopAlpeccaCapabilityLease(recorderLease);
      return;
    }
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    if (sequence !== alpeccaPushToTalkSequence || alpeccaChat.classList.contains("hidden")) {
      stream.getTracks().forEach((track) => track.stop());
      await stopAlpeccaCapabilityLease(recorderLease);
      return;
    }
    alpeccaPushToTalkStream = stream;
    const recorder = new MediaRecorder(stream);
    alpeccaPushToTalkRecorder = recorder;
    alpeccaPushToTalkChunks = [];
    recorder.ondataavailable = (event) => {
      if (
        sequence === alpeccaPushToTalkSequence
        && alpeccaPushToTalkRecorder === recorder
        && event.data.size
      ) {
        alpeccaPushToTalkChunks.push(event.data);
      }
    };
    recorder.onerror = () => {
      if (sequence !== alpeccaPushToTalkSequence || alpeccaPushToTalkRecorder !== recorder) return;
      void cancelAlpeccaPushToTalk();
      showAlpeccaProfileLine("Microphone recording stopped unexpectedly.", "listening");
    };
    recorder.onstop = () => {
      recorder.ondataavailable = null;
      recorder.onstop = null;
      recorder.onerror = null;
      if (sequence !== alpeccaPushToTalkSequence || alpeccaPushToTalkRecorder !== recorder) return;
      clearAlpeccaPushToTalkStopTimer();
      const chunks = alpeccaPushToTalkChunks;
      const mimeType = recorder.mimeType || "audio/webm";
      alpeccaPushToTalkRecorder = null;
      alpeccaPushToTalkChunks = [];
      stopAlpeccaPushToTalkStream();
      void transcribeAlpeccaPushToTalk(new Blob(chunks, { type: mimeType }), sequence, recorderLease);
    };
    stream.getAudioTracks().forEach((track) => {
      track.onended = () => {
        if (alpeccaPushToTalkStream === stream) void cancelAlpeccaPushToTalk();
      };
    });
    recorder.start();
    const stopTimer = window.setTimeout(() => {
      if (alpeccaPushToTalkStopTimer !== stopTimer) return;
      alpeccaPushToTalkStopTimer = null;
      if (sequence !== alpeccaPushToTalkSequence || alpeccaPushToTalkRecorder !== recorder) return;
      if (recorder.state === "recording") recorder.stop();
    }, ALPECCA_PUSH_TO_TALK_MAX_MS);
    alpeccaPushToTalkStopTimer = stopTimer;
    setAlpeccaPushToTalkState("recording");
    showAlpeccaProfileLine("Listening - tap the microphone again to send.", "listening");
  } catch (error) {
    if (sequence !== alpeccaPushToTalkSequence) {
      if (lease) await stopAlpeccaCapabilityLease(lease);
      return;
    }
    await cancelAlpeccaPushToTalk();
    const detail = error instanceof Error && /^(Live House|Microphone)/.test(error.message)
      ? error.message
      : "Microphone access was unavailable or denied.";
    showAlpeccaProfileLine(detail, "listening");
  }
}

async function closeAlpeccaCamera(stopLease = true) {
  alpeccaCameraSequence += 1;
  alpeccaCameraStream?.getTracks().forEach((track) => {
    track.onended = null;
    track.stop();
  });
  alpeccaCameraStream = null;
  alpeccaCameraVideo.pause();
  alpeccaCameraVideo.srcObject = null;
  alpeccaCameraPreview.classList.add("hidden");
  alpeccaCameraOpenButton.setAttribute("aria-pressed", "false");
  if (stopLease) await stopAlpeccaCapabilityLease("camera_frame");
}

async function openAlpeccaCamera() {
  if (!navigator.mediaDevices?.getUserMedia) {
    showAlpeccaProfileLine("This browser does not provide camera access.", "listening");
    return;
  }
  await cancelAlpeccaPushToTalk();
  await closeAlpeccaCamera();
  if (alpeccaChat.classList.contains("hidden")) return;
  const sequence = ++alpeccaCameraSequence;
  let lease: AlpeccaCapabilityLease | null = null;
  try {
    lease = await acquireAlpeccaCapabilityLease("camera_frame");
    if (sequence !== alpeccaCameraSequence || alpeccaChat.classList.contains("hidden")) {
      await stopAlpeccaCapabilityLease(lease);
      return;
    }
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 1280 }, facingMode: { ideal: "environment" } },
      audio: false,
    });
    if (sequence !== alpeccaCameraSequence || alpeccaChat.classList.contains("hidden")) {
      stream.getTracks().forEach((track) => track.stop());
      await stopAlpeccaCapabilityLease(lease);
      return;
    }
    alpeccaCameraStream = stream;
    alpeccaCameraVideo.srcObject = stream;
    alpeccaCameraPreview.classList.remove("hidden");
    alpeccaCameraOpenButton.setAttribute("aria-pressed", "true");
    stream.getVideoTracks()[0].onended = () => {
      if (alpeccaCameraStream === stream) void closeAlpeccaCamera();
    };
    await alpeccaCameraVideo.play();
  } catch (error) {
    if (sequence !== alpeccaCameraSequence) {
      if (lease) await stopAlpeccaCapabilityLease(lease);
      return;
    }
    await closeAlpeccaCamera();
    const detail = error instanceof Error && /^(Live House|Camera)/.test(error.message)
      ? error.message
      : "Camera access was unavailable or denied.";
    showAlpeccaProfileLine(detail, "listening");
  }
}

async function sendAlpeccaCameraFrame() {
  if (!alpeccaCameraStream || !alpeccaCameraVideo.videoWidth || !alpeccaCameraVideo.videoHeight) {
    showAlpeccaProfileLine("The camera is still preparing a frame.", "listening");
    return;
  }
  const lease = alpeccaCapabilityLeases.get("camera_frame");
  if (!alpeccaCapabilityLeaseIsUsable(lease, "camera_frame")) {
    await closeAlpeccaCamera();
    showAlpeccaProfileLine("Camera permission expired. Open the camera again.", "listening");
    return;
  }
  const scale = Math.min(1, 768 / Math.max(alpeccaCameraVideo.videoWidth, alpeccaCameraVideo.videoHeight));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(alpeccaCameraVideo.videoWidth * scale));
  canvas.height = Math.max(1, Math.round(alpeccaCameraVideo.videoHeight * scale));
  canvas.getContext("2d")?.drawImage(alpeccaCameraVideo, 0, 0, canvas.width, canvas.height);
  const image = canvas.toDataURL("image/jpeg", 0.82);
  const message = alpeccaChatInput.value.trim();
  await closeAlpeccaCamera(false);
  await sendAlpeccaChat(message, image, "", null, lease);
}

updateAlpeccaSpokenRepliesButton();
setAlpeccaPushToTalkState("idle");

function setAlpeccaProfileMode(mode: string, featureId = alpeccaActiveProfileFeature) {
  alpeccaProfileMode = mode;
  alpeccaActiveProfileFeature = featureId;
  if (mode === "thinking") setAlpeccaIntent("thinking", "player");
  else if (mode === "talking") setAlpeccaIntent("replying", "player");
  else if (mode === "observing") setAlpeccaIntent("observing", alpeccaLastSeenLabel || currentOfficeRoom().name);
  else if (mode === "listening") setAlpeccaIntent("listening", "player");
  alpeccaChat.dataset.mode = mode;
  alpeccaChat.dataset.feature = featureId;
  alpeccaProfileModeEl.textContent = featureId ? `${featureId} / ${mode}` : mode;
  alpeccaProfileSeenEl.textContent = alpeccaLastSeenLabel
    ? `Saw: ${alpeccaLastSeenLabel}${alpeccaLastQuestion ? ` | ${alpeccaLastQuestion}` : ""}`
    : "Watching the room...";
  alpeccaProfileGlitchTimer = Math.max(alpeccaProfileGlitchTimer, mode === "glitch" ? 0.8 : 0.28);
  updateAlpeccaChatExpressionPortrait(true);
}

function showAlpeccaProfileLine(text: string, mode = "talking", featureId = alpeccaActiveProfileFeature) {
  alpeccaChat.classList.remove("hidden");
  alpeccaChat.scrollTop = 0;
  alpecca.showcaseTimer = 0;
  alpeccaChatLine.textContent = text;
  setAlpeccaProfileMode(mode, featureId);
  updateAlpeccaChatExpressionPortrait(true);
}

const ALPECCA_CHAT_REJECTION_BODY_MAX_CHARS = 2_048;
const ALPECCA_CHAT_REJECTION_FIELD_MAX_CHARS = 160;

function boundedAlpeccaChatRejectionField(value: unknown) {
  if (typeof value !== "string") return "";
  return value.replace(/\s+/g, " ").trim().slice(0, ALPECCA_CHAT_REJECTION_FIELD_MAX_CHARS);
}

async function readAlpeccaChatRejection(response: Response, attachmentKind: "" | "image" | "file" = "") {
  let detailText = "";
  let code = "";
  let reason = "";
  try {
    const body = await response.text();
    if (body.length <= ALPECCA_CHAT_REJECTION_BODY_MAX_CHARS) {
      const payload = JSON.parse(body) as Record<string, unknown>;
      code = boundedAlpeccaChatRejectionField(payload.code);
      reason = boundedAlpeccaChatRejectionField(payload.reason);
      const detail = payload.detail;
      if (typeof detail === "string") {
        detailText = boundedAlpeccaChatRejectionField(detail);
      } else if (detail && typeof detail === "object" && !Array.isArray(detail)) {
        const detailPayload = detail as Record<string, unknown>;
        code = boundedAlpeccaChatRejectionField(detailPayload.code) || code;
        reason = boundedAlpeccaChatRejectionField(detailPayload.reason);
        detailText = boundedAlpeccaChatRejectionField(detailPayload.message);
      }
    }
  } catch {
    // A malformed or unreadable rejection remains terminal, with a generic message.
  }

  if (code === "attachment_rejected") {
    if (attachmentKind === "file") {
      const attachmentMessage: Record<string, string> = {
        "invalid-source-ref": "That server file reference was rejected.",
        "raw-file-payload-disabled": "Raw file data is disabled; attach the server file reference instead.",
        "source-ref-house-only": "Server file references are only available through House HQ.",
        "traversal": "That file is outside the allowed file rooms.",
        "root-not-allowed": "That file room is not allowed.",
        "file-not-found": "That server file reference is no longer available.",
        "multiple-attachments": "Send either a file or an image in one message, not both.",
        "binary": "Only readable text files can be attached.",
        "unsupported-mime": "That file type is not supported.",
        "size-limit": "That file is too large to attach.",
      };
      return {
        message: attachmentMessage[reason] || "That file attachment was rejected by the backend.",
        code: reason ? `${code}:${reason}` : code,
      };
    }
    const attachmentMessage: Record<string, string> = {
      "size-limit": "That image is too large to send.",
      "unsupported-mime": "That image format is not supported.",
      "mime-mismatch": "That image's format does not match its contents.",
      "invalid-dimensions": "That image's dimensions are not supported.",
      "pixel-limit": "That image's dimensions are too large.",
      "invalid-bytes": "That image could not be read.",
      "malformed-data-url": "That image could not be read.",
      "malformed-base64": "That image could not be read.",
    };
    return {
      message: attachmentMessage[reason] || "That image was rejected by the backend.",
      code: reason ? `${code}:${reason}` : code,
    };
  }

  return {
    message: detailText
      ? `Request rejected: ${detailText}`
      : `The backend rejected that request (HTTP ${response.status}).`,
    code,
  };
}

function alpeccaSourceRefLabel(sourceRef: AlpeccaSourceRef) {
  return `${sourceRef.root}/${sourceRef.rel.replace(/^\/+/, "")}`;
}

function alpeccaSourceRefFileName(sourceRef: AlpeccaSourceRef) {
  const fileName = sourceRef.rel.replace(/\\/g, "/").split("/").filter(Boolean).pop() || sourceRef.rel;
  return fileName.length > 96 ? `...${fileName.slice(-93)}` : fileName;
}

const ALPECCA_ATTACHABLE_TEXT_EXTENSIONS = new Set([
  "cfg", "conf", "csv", "css", "html", "ini", "js", "json", "log", "md",
  "py", "toml", "ts", "txt", "xml", "yaml", "yml",
]);

function isAlpeccaAttachableTextFile(relativePath: string) {
  const fileName = relativePath.replace(/\\/g, "/").split("/").filter(Boolean).pop() || "";
  const extension = fileName.includes(".") ? fileName.split(".").pop()?.toLowerCase() || "" : "";
  return ALPECCA_ATTACHABLE_TEXT_EXTENSIONS.has(extension);
}

function prepareAlpeccaFileAttachment(sourceRef: AlpeccaSourceRef) {
  if (alpeccaAiAwaitingReply) {
    setAlpeccaSystemsNotice("Wait for the current reply before attaching another file.");
    return;
  }
  if (!sourceRef.root || !sourceRef.rel) {
    setAlpeccaSystemsNotice("That file reference is incomplete.");
    return;
  }
  closeAlpeccaSystems();
  openAlpeccaChat();
  alpeccaPendingSourceRef = sourceRef;
  alpeccaChatInput.value = "Please inspect this file.";
  const fileName = alpeccaSourceRefFileName(sourceRef);
  alpeccaChatInput.placeholder = `Ask about ${fileName}`;
  showAlpeccaProfileLine(`${fileName} from ${sourceRef.root} is ready to attach by server reference.`, "listening", "files");
  appendAlpeccaLog("System", `Selected ${alpeccaSourceRefLabel(sourceRef)} by server reference.`);
  alpeccaChatInput.focus();
  alpeccaChatInput.select();
}

function compactAlpeccaAttachmentProvenance(value: unknown) {
  const provenance = boundedAlpeccaChatRejectionField(value);
  const sha256 = provenance.match(/^(?:sha256:)?([a-f0-9]{64})$/i);
  return sha256 ? `sha256:${sha256[1].slice(0, 12)}...` : provenance.slice(0, 56);
}

function showAlpeccaAttachmentReceipt(payload: Record<string, unknown>, sourceRef: AlpeccaSourceRef) {
  const receipt = systemRecord(payload.attachment);
  const source = systemRecord(receipt.source);
  const envelope = systemRecord(receipt.envelope);
  const status = boundedAlpeccaChatRejectionField(receipt.status);
  const encoding = boundedAlpeccaChatRejectionField(receipt.encoding);
  const provenance = compactAlpeccaAttachmentProvenance(
    envelope.provenance || source.sha256,
  );
  if (!status && !provenance) return;
  const summary = [
    status || "resolved",
    encoding,
    receipt.excerpt_truncated === true ? "excerpt truncated" : "",
    provenance,
  ].filter(Boolean).join(" / ");
  const returnedSourceRef = {
    root: boundedAlpeccaChatRejectionField(source.root_id) || sourceRef.root,
    rel: typeof source.relative_path === "string" && source.relative_path.trim()
      ? source.relative_path.trim()
      : sourceRef.rel,
  };
  appendAlpeccaLog("System", `Attachment: ${summary}`);
  alpeccaProfileSeenEl.textContent = `${alpeccaSourceRefFileName(returnedSourceRef)}: ${summary}`;
}

function finishAlpeccaChatFailure(
  requestId: string,
  message: string,
  attachmentLabel = "",
  attachmentStatus = "failed",
) {
  if (alpeccaAiPendingPlayerRequestId !== requestId) return;
  rememberCompletedAlpeccaRequest(requestId);
  alpeccaAiAwaitingReply = false;
  alpeccaAiReplyStartedAt = 0;
  alpeccaAiSlowReplyNoticeShown = false;
  alpeccaAiExtendedReplyNoticeShown = false;
  alpeccaAiPendingPlayerRequestId = "";
  alpeccaAiLastPlayerMessage = "";
  alpeccaVoiceSession.setConversationState("listening", "chat request failed");
  appendAlpeccaLog("System", message);
  showAlpeccaProfileLine(message, "listening");
  if (attachmentLabel) alpeccaProfileSeenEl.textContent = `${attachmentLabel}: ${attachmentStatus}`;
  showMessage(message, 5);
}

async function sendAlpeccaChat(
  text: string,
  image = "",
  privatePerception = "",
  sourceRef: AlpeccaSourceRef | null = null,
  providedLease: AlpeccaCapabilityLease | null = null,
) {
  const trimmed = text.trim();
  if (!trimmed && !image && !sourceRef) return;
  const capabilityPurpose: AlpeccaCapabilityPurpose | null = sourceRef
    ? "file_source_ref"
    : image
      ? "camera_frame"
      : null;
  let capabilityLease = providedLease;
  if (capabilityPurpose) {
    try {
      capabilityLease = capabilityLease || await acquireAlpeccaCapabilityLease(capabilityPurpose, sourceRef);
      if (!alpeccaCapabilityLeaseIsUsable(capabilityLease, capabilityPurpose)) {
        throw new Error(`${alpeccaCapabilityLabel(capabilityPurpose)} permission expired.`);
      }
      if (alpeccaChat.classList.contains("hidden")) {
        await stopAlpeccaCapabilityLease(capabilityLease);
        return;
      }
    } catch (error) {
      if (capabilityLease) await stopAlpeccaCapabilityLease(capabilityLease);
      if (sourceRef && !alpeccaChat.classList.contains("hidden")) {
        alpeccaPendingSourceRef = sourceRef;
        alpeccaChatInput.placeholder = `Ask about ${alpeccaSourceRefFileName(sourceRef)}`;
      }
      const detail = error instanceof Error ? error.message : "Permission was not granted.";
      showAlpeccaProfileLine(detail, "listening");
      return;
    }
  }
  const releaseCapabilityLease = async () => {
    const lease = capabilityLease;
    capabilityLease = null;
    if (lease) await stopAlpeccaCapabilityLease(lease);
  };
  const promptText = trimmed || (sourceRef ? "Please inspect this attached file." : "I'm showing you something through the camera right now.");
  const logText = sourceRef
    ? `${promptText} [attached ${alpeccaSourceRefLabel(sourceRef)}]`
    : image
      ? (trimmed ? `${trimmed} [camera frame]` : "Shared a camera frame.")
      : trimmed;

  alpeccaVoiceSession.interrupt({ clearQueue: true, reason: "new creator turn" });
  alpeccaVoiceSession.setConversationState("thinking", "waiting for Alpecca's reply");
  focusAlpecca(4.2, "idleDown");
  alpecca.expressiveTimer = 0;
  alpecca.walkPauseTimer = Math.max(alpecca.walkPauseTimer, 5.5);
  alpecca.dwellTimer = Math.max(alpecca.dwellTimer, 1.2);
  alpeccaChatInput.value = "";
  setAlpeccaProfileMode("thinking");
  alpeccaChatLine.textContent = "Alpecca is thinking...";
  appendAlpeccaLog("Player", logText);
  setAlpeccaActivity("Alpecca is thinking about your message.", "think");

  const requestId = `house-chat-${Date.now().toString(36)}-${(++alpeccaAiRequestSequence).toString(36)}`;
  alpeccaAiAwaitingReply = true;
  alpeccaAiPendingPlayerRequestId = requestId;
  alpeccaAiLastPlayerMessage = promptText;
  alpeccaAiReplyStartedAt = performance.now();
  alpeccaAiSlowReplyNoticeShown = false;
  alpeccaAiExtendedReplyNoticeShown = false;
  alpeccaPlayerChatQuietTimer = Math.max(alpeccaPlayerChatQuietTimer, 42);
  alpeccaWorldTickTimer = Math.max(alpeccaWorldTickTimer, 18);
  alpeccaPerceptionSendTimer = Math.max(alpeccaPerceptionSendTimer, 18);
  showMessage("Alpecca is thinking...", 4);
  appendAlpeccaLog("System", "Sent to live Alpecca core.");
  // Primary route for main app chat: shared house runtime API. Optional tooling
  // (including Discord) can reuse this same endpoint, but the house app should
  // not depend on Discord for runtime behavior.
  const inboundPrompt = {
    text: promptText,
    channel: "house-chat",
    source: "house-chat",
    sender: "player",
    room: currentOfficeRoom().name,
    situation: alpeccaContextPrefix(),
    context: alpeccaContextPrefix(),
    speaker: "guest",
    request_id: requestId,
    ...(image ? { image } : {}),
    ...(privatePerception ? { private_perception: privatePerception } : {}),
    ...(sourceRef ? { source_ref: { root: sourceRef.root, rel: sourceRef.rel } } : {}),
  };
  const inboundUrl = alpeccaUrlWithParams(`${alpeccaAiBaseUrl}/channel/house-hq`);
  if (alpeccaAiBaseUrl && inboundUrl) {
    const headers = capabilityLease
      ? alpeccaCapabilityLeaseHeaders(capabilityLease, { "Content-Type": "application/json" })
      : new Headers({ "Content-Type": "application/json" });
    // Once the request body has been sent, we cannot know whether the backend
    // committed work when the transport fails. Never resend it over WebSocket:
    // one House request ID must remain one model/tool transaction.
    const controller = new AbortController();
    if (capabilityLease) alpeccaCapabilityChannelRequest = controller;
    try {
      const response = await alpeccaBackendFetch(inboundUrl, {
        method: "POST",
        headers,
        body: JSON.stringify(inboundPrompt),
        signal: controller.signal,
      });
      if (response.ok) {
        let payload: Record<string, unknown>;
        try {
          payload = (await response.json()) as Record<string, unknown>;
        } catch {
          await releaseCapabilityLease();
          finishAlpeccaChatFailure(requestId, "The live House response was invalid.");
          return;
        }
        await releaseCapabilityLease();
        const replyPayload = {
          type: "reply",
          ...(payload && typeof payload === "object" ? payload : {}),
          request_id: requestId,
          source: "house-chat",
        } as AlpeccaAiMessage;
        handleAlpeccaAiMessage(JSON.stringify(replyPayload));
        if (sourceRef) showAlpeccaAttachmentReceipt(payload, sourceRef);
        return;
      }
      if (response.status >= 400 && response.status < 500) {
        const rejection = await readAlpeccaChatRejection(response, sourceRef ? "file" : image ? "image" : "");
        await releaseCapabilityLease();
        appendAlpeccaLog(
          "System",
          `House live chat request rejected (${response.status}${rejection.code ? `, ${rejection.code}` : ""}).`,
        );
        const attachmentLabel = sourceRef
          ? alpeccaSourceRefFileName(sourceRef)
          : "";
        finishAlpeccaChatFailure(requestId, rejection.message, attachmentLabel, "rejected");
        return;
      }
      if (sourceRef) {
        await releaseCapabilityLease();
        finishAlpeccaChatFailure(
          requestId,
          `The attachment request failed (HTTP ${response.status}).`,
          alpeccaSourceRefFileName(sourceRef),
        );
        return;
      }
      await releaseCapabilityLease();
      finishAlpeccaChatFailure(requestId, `The live House core could not complete this request (HTTP ${response.status}).`);
      return;
    } catch {
      if (controller.signal.aborted && alpeccaChat.classList.contains("hidden")) {
        await releaseCapabilityLease();
        return;
      }
      if (sourceRef) {
        await releaseCapabilityLease();
        finishAlpeccaChatFailure(
          requestId,
          "The attachment request could not reach the live backend.",
          alpeccaSourceRefFileName(sourceRef),
        );
        return;
      }
      await releaseCapabilityLease();
      appendAlpeccaLog("System", "The live request was submitted, but its connection is still settling. Waiting for its original result...");
      showAlpeccaProfileLine("The live request is still running. Waiting for its original result...", "thinking");
      return;
    } finally {
      if (alpeccaCapabilityChannelRequest === controller) alpeccaCapabilityChannelRequest = null;
    }
  }

  if (sourceRef) {
    await releaseCapabilityLease();
    finishAlpeccaChatFailure(
      requestId,
      "The attachment request requires the live House backend.",
      alpeccaSourceRefFileName(sourceRef),
    );
    return;
  }

  if (alpeccaAiStatus === "live" && alpeccaSocket?.readyState === WebSocket.OPEN) {
    const socketMessage = {
      text: promptText,
      context: alpeccaContextPrefix(),
      source: "house-chat",
      request_id: requestId,
      ...(image ? { image } : {}),
      ...(privatePerception ? { private_perception: privatePerception } : {}),
      ...(capabilityLease ? {
        capability_lease: capabilityLease.token,
        capability_purpose: capabilityLease.purpose,
        capability_connection: capabilityLease.connectionId,
      } : {}),
    };
    const wsLease = capabilityLease;
    if (wsLease) {
      alpeccaAiPendingCapabilityLease = { requestId, lease: wsLease };
      capabilityLease = null;
    }
    try {
      alpeccaSocket.send(JSON.stringify(socketMessage));
      return;
    } catch {
      if (wsLease && alpeccaAiPendingCapabilityLease?.lease === wsLease) {
        alpeccaAiPendingCapabilityLease = null;
        capabilityLease = wsLease;
      }
    }
  }

  await releaseCapabilityLease();

  if (image) {
    finishAlpeccaChatFailure(requestId, "The camera frame requires the live House connection.");
    return;
  }

  if (alpeccaAiStatus === "token") {
    const sessionLine = "Live Alpecca needs an authorized session. Open the backend app to sign in, then reconnect House HQ.";
    alpeccaAiAwaitingReply = false;
    alpeccaAiReplyStartedAt = 0;
    alpeccaAiSlowReplyNoticeShown = false;
    alpeccaAiPendingPlayerRequestId = "";
    alpeccaAiLastPlayerMessage = "";
    alpeccaVoiceSession.setConversationState("listening", "backend session required");
    appendAlpeccaLog("System", sessionLine);
    showAlpeccaProfileLine(sessionLine, "listening");
    showMessage("Alpecca backend session required.", 4.5);
    return;
  }

  alpeccaAiAwaitingReply = false;
  alpeccaAiReplyStartedAt = 0;
  alpeccaAiSlowReplyNoticeShown = false;
  alpeccaAiPendingPlayerRequestId = "";
  alpeccaAiLastPlayerMessage = "";
  alpeccaVoiceSession.setConversationState("listening", "offline fallback");
  if (!alpeccaAiOfflineNoticeShown) {
    showMessage("Live Alpecca is offline. Using local game dialogue.", 3.5);
    alpeccaAiOfflineNoticeShown = true;
  }
  window.setTimeout(() => {
    const localLine = getAlpeccaDialogue();
    appendAlpeccaLog("Alpecca", localLine);
    if (alpeccaSpokenRepliesEnabled) startAlpeccaSpeech(localLine);
    showAlpeccaProfileLine(localLine, "listening");
    showMessage(localLine, 5);
  }, 250);
}

async function askAlpeccaAboutCurrentRoom() {
  const room = currentOfficeRoom();
  const memory = environmentMemoryForRoom(room.id);
  const question = memory.lastQuestion || `What should I inspect next in ${room.name}?`;
  const prompt = [
    `Room focus: ${room.name}.`,
    `Purpose: ${room.purpose}`,
    `System status: ${roomIsActive(room) ? "online" : "offline"}.`,
    memory.lastSeen ? `Last seen: ${memory.lastSeen}.` : "No room observation has been recorded yet.",
    `Question: ${question}`,
    "Answer as Alpecca in one useful in-world update.",
  ].join(" ");
  alpeccaChat.classList.remove("hidden");
  appendAlpeccaLog("Room", `${room.name}: ${question}`);
  setAlpeccaActivity(`Alpecca is reading ${room.name}.`, "observe");
  showAlpeccaProfileLine(`Asking ${room.name}: ${question}`, "thinking", room.id === "entry" ? "home" : "");
  try {
    const response = await alpeccaBackendFetch(alpeccaUrlWithParams(`${alpeccaAiBaseUrl}/cognition/rooms/${encodeURIComponent(room.id)}/review`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        room_name: room.name,
        purpose: room.purpose,
        status: roomIsActive(room) ? "online" : "offline",
        last_seen: memory.lastSeen || "",
        question,
      }),
    });
    if (!response.ok) throw new Error(`room review ${response.status}`);
    const review = await response.json();
    const line = String(review.line || "");
    if (line) {
      appendAlpeccaLog("Alpecca", line);
      startAlpeccaSpeech(line);
      showAlpeccaProfileLine(line, "talking", room.id === "entry" ? "home" : "");
      showMessage(line, 5);
      if (review.question) {
        memory.lastQuestion = String(review.question);
        saveAlpeccaAppMemory();
      }
      if (review.proposal_id) pulseAlpeccaImprovementQueue(3.4);
      return;
    }
  } catch {
    // Fall back to normal chat if the cognition endpoint is unavailable.
  }
  void sendAlpeccaChat(prompt);
}

async function runAlpeccaLivingLoop() {
  const room = currentOfficeRoom();
  alpeccaChat.classList.remove("hidden");
  focusAlpecca(3.2, "idleDown");
  appendAlpeccaLog("System", `Running living loop in ${room.name}.`);
  setAlpeccaActivity("Alpecca is activating her world-learning loop.", "observe", 4);
  showAlpeccaProfileLine("Listening to the room, checking creator context, and choosing one grounded question...", "thinking", "home");
  try {
    const response = await alpeccaBackendFetch(alpeccaUrlWithParams(`${alpeccaAiBaseUrl}/cognition/world-tick`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: "house_hq_hot_tab", room: room.id }),
    });
    if (!response.ok) throw new Error(`world tick ${response.status}`);
    const data = await response.json();
    setAlpeccaLivingState(data, data.line || data.question || "");
    routeAlpeccaToLivingLoopTarget(data);
    pulseAlpeccaActivatedSystem(data.activated_system?.id || "");
    const line = String(data.line || data.question || "I asked myself one grounded question about my world.");
    appendAlpeccaLog("Alpecca", line);
    showAlpeccaProfileLine(line, "thinking", "home");
    showMessage(line, 5.5);
    if (data.proposal || data.engagement_proposal) pulseAlpeccaImprovementQueue(3.4);
    return data;
  } catch {
    const line = "I could not activate my living loop from the core right now.";
    appendAlpeccaLog("System", line);
    showAlpeccaProfileLine(line, "listening", "home");
    showMessage(line, 4.5);
    return null;
  }
}

function alpeccaAutonomyBusy() {
  return (
    !alpecca.ready ||
    alpeccaPlayerChatQuietTimer > 0 ||
    alpeccaWorldTickInFlight ||
    alpeccaAiStatus !== "live" ||
    alpeccaAiAwaitingReply ||
    alpeccaLiveAttentionTimer > 0 ||
    alpecca.attentionTimer > 0 ||
    alpecca.waveTimer > 0 ||
    alpecca.expressiveTimer > 0 ||
    alpecca.inspectTimer > 0.4 ||
    !alpeccaChat.classList.contains("hidden") ||
    !alpeccaWorkshop.classList.contains("hidden")
  );
}

async function runAlpeccaQuietWorldTick(reason = "house_hq_autonomous_cadence") {
  if (alpeccaPlayerChatQuietTimer > 0 || alpeccaWorldTickInFlight || alpeccaAiStatus !== "live") return null;
  const room = currentOfficeRoom();
  alpeccaWorldTickInFlight = true;
  try {
    const response = await alpeccaBackendFetch(alpeccaUrlWithParams(`${alpeccaAiBaseUrl}/cognition/world-tick`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason, room: room.id, quiet: true }),
    });
    if (!response.ok) throw new Error(`quiet world tick ${response.status}`);
    const data = await response.json();
    if (data?.deferred === true) return data;
    setAlpeccaLivingState(data, data.line || data.question || "");
    routeAlpeccaToLivingLoopTarget(data);
    pulseAlpeccaActivatedSystem(data.activated_system?.id || "");
    const featureId = featureForLivingLoop(data);
    const targetRoomId = livingLoopTargetRoomId(data);
    const targetRoom = officeRooms.find((item) => item.id === targetRoomId) ?? room;
    if (featureId) void runAlpeccaFeatureToolBridge(featureId, targetRoom, false);
    const line = String(data.line || data.question || "Alpecca asked herself one grounded world question.");
    appendAlpeccaLog("System", `Living loop: ${line}`);
    setAlpeccaActivity(`Alpecca is recursively checking ${targetRoom.name}.`, "observe", 4.2);
    if (alpeccaCuriosityNoticeTimer <= 0) {
      showMessage(line, 4.2);
      alpeccaCuriosityNoticeTimer = 14;
    }
    if (data.proposal || data.engagement_proposal) pulseAlpeccaImprovementQueue(3.4);
    return data;
  } catch {
    alpeccaAiOfflineNoticeShown = false;
    return null;
  } finally {
    alpeccaWorldTickInFlight = false;
  }
}

function autonomyStateToLivingLoop(state: AlpeccaAutonomyState): AlpeccaAiMessage["living_loop"] | null {
  const question = String(state.last_living_question || "").trim();
  const line = String(state.last_living_line || "").trim();
  const roomName = String(state.last_living_room || currentOfficeRoom().name).trim();
  if (!question && !line && !state.last_living_at) return null;
  const systemId = String(state.last_living_system || "").trim();
  const intentName = String(state.current_intent?.name || "questioning");
  return {
    ok: true,
    phase: intentName,
    line,
    question: question || line || "What should I understand next from this room?",
    activated_system: systemId
      ? {
          id: systemId,
          label: systemId.replace(/_/g, " "),
          status: "background",
          summary: String(state.last_living_reason || "autonomous living loop"),
        }
      : undefined,
    room: { name: roomName },
    intent: {
      name: intentName,
      reason: String(state.current_intent?.reason || state.last_living_reason || "Alpecca is continuing her living loop."),
      target: String(state.current_intent?.target || roomName),
    },
    self_feedback: state.last_living_self_feedback,
    next_action: state.last_living_next_action,
    engagement_proposal: state.last_living_engagement_proposal,
    memory_id: typeof state.last_living_memory_id === "number" ? state.last_living_memory_id : undefined,
    journal_id: typeof state.last_living_journal_id === "number" ? state.last_living_journal_id : undefined,
  };
}

async function pollAlpeccaAutonomyState() {
  if (alpeccaAutonomyPollInFlight || alpeccaAiStatus !== "live" || !alpeccaAiBaseUrl) return;
  alpeccaAutonomyPollInFlight = true;
  try {
    const response = await alpeccaBackendFetch(alpeccaUrlWithParams(`${alpeccaAiBaseUrl}/cognition/autonomy-state`));
    if (!response.ok) throw new Error(`autonomy-state ${response.status}`);
    const data = (await response.json()) as AlpeccaAutonomyState;
    const key = [
      data.last_living_at || 0,
      data.last_living_observation_id || "",
      data.last_living_memory_id || "",
      data.last_living_journal_id || "",
      data.last_living_question || "",
    ].join("|");
    if (!key || key === alpeccaLastAutonomyKey) return;
    const loop = autonomyStateToLivingLoop(data);
    if (!loop) return;
    alpeccaLastAutonomyKey = key;
    setAlpeccaLivingState(loop, loop.line || loop.question || "");
    routeAlpeccaToLivingLoopTarget(loop);
    pulseAlpeccaActivatedSystem(loop.activated_system?.id || "");
    setAlpeccaActivity("Alpecca is carrying a background question from her core.", "observe", 3.8);
  } catch {
    // Polling is deliberately quiet; WebSocket and manual world ticks still handle visible failures.
  } finally {
    alpeccaAutonomyPollInFlight = false;
  }
}

function updateAlpeccaAutonomousWorldTick(dt: number) {
  if (alpeccaPlayerChatQuietTimer > 0) alpeccaPlayerChatQuietTimer = Math.max(0, alpeccaPlayerChatQuietTimer - dt);
  alpeccaAutonomyPollTimer -= dt;
  if (alpeccaAutonomyPollTimer <= 0) {
    alpeccaAutonomyPollTimer = 16;
    void pollAlpeccaAutonomyState();
  }
  alpeccaWorldTickTimer -= dt;
  if (alpeccaWorldTickTimer > 0) return;
  if (alpeccaAutonomyBusy()) {
    alpeccaWorldTickTimer = 10;
    return;
  }
  void runAlpeccaQuietWorldTick();
  alpeccaWorldTickTimer = alpeccaAppMemory.curiositySweeps < 2 ? 44 : 86;
}

async function reviewAlpeccaReplies() {
  alpeccaChat.classList.remove("hidden");
  focusAlpecca(3.2, "idleDown");
  appendAlpeccaLog("System", "Reviewing recent replies for grounding.");
  setAlpeccaActivity("Alpecca is reviewing recent replies.", "think", 3.4);
  showAlpeccaProfileLine("Reviewing recent replies for grounding...", "thinking", "memory");
  try {
    const response = await alpeccaBackendFetch(alpeccaUrlWithParams(`${alpeccaAiBaseUrl}/cognition/chat/review`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ limit: 8 }),
    });
    if (!response.ok) throw new Error(`chat review ${response.status}`);
    const data = await response.json();
    const review = data.review || {};
    const reviewed = Number(review.reviewed || 0);
    const riskCount = Number(review.risk_count || 0);
    const score = Number(review.grounding_score ?? 1);
    const percent = Math.round(score * 100);
    const line = riskCount
      ? `I reviewed ${reviewed} replies. Grounding score ${percent}%; I found ${riskCount} risk${riskCount === 1 ? "" : "s"} and added it to my improvement queue.`
      : `I reviewed ${reviewed} replies. Grounding score ${percent}%; no obvious grounding risks found.`;
    appendAlpeccaLog("Alpecca", line);
    if (data.proposal) appendAlpeccaLog("System", "Workshop proposal created: improve reply grounding.");
    showAlpeccaProfileLine(line, riskCount ? "thinking" : "talking", "memory");
    showMessage(line, 5);
    if (data.proposal) pulseAlpeccaImprovementQueue(3.8);
    return data;
  } catch {
    const line = "I could not review my recent replies right now.";
    appendAlpeccaLog("System", line);
    showAlpeccaProfileLine(line, "listening", "memory");
    showMessage(line, 4);
    return null;
  }
}

function summarizeDoctorReport(data: any) {
  const sections = Array.isArray(data?.sections) ? data.sections : [];
  const priority = ["Model", "Voice", "Mindscape", "House HQ", "Alpecca app", "Remote preview", "Senses"];
  const needs = sections
    .filter((section: any) => {
      const status = String(section?.status || "");
      return status && !["ready", "cloud_ready", "active"].includes(status);
    })
    .sort((a: any, b: any) => priority.indexOf(String(a?.name)) - priority.indexOf(String(b?.name)));
  const first = needs[0];
  if (!first) {
    return "Doctor check: House HQ, Alpecca app, Mindscape, model, and original voice all report ready.";
  }
  const name = String(first.name || "System");
  const detail = String(first.detail || "needs attention");
  const setupStep = name === "Mindscape" && Array.isArray(data?.mindscape_setup?.steps)
    ? data.mindscape_setup.steps.find((step: any) => !step?.done)
    : null;
  const setupCommand = setupStep?.command ? ` Next: ${String(setupStep.command)}` : "";
  const fix = String(first.fix || (Array.isArray(data?.next_actions) ? data.next_actions[0] : "") || "");
  return `Doctor check: ${name} is ${first.status || "not ready"}. ${detail}${fix ? ` Fix: ${fix}` : ""}${setupCommand}`;
}

async function runAlpeccaDoctorCheck() {
  alpeccaChat.classList.remove("hidden");
  focusAlpecca(3.2, "idleDown");
  appendAlpeccaLog("System", "Checking Alpecca core health.");
  setAlpeccaActivity("Alpecca is checking her core systems.", "think", 3.4);
  showAlpeccaProfileLine("Checking House HQ, app core, voice, model, and Mindscape...", "thinking", "home");
  try {
    const response = await alpeccaBackendFetch(alpeccaUrlWithParams(`${alpeccaAiBaseUrl}/system/doctor`));
    if (!response.ok) throw new Error(`doctor ${response.status}`);
    const data = await response.json();
    const line = summarizeDoctorReport(data);
    appendAlpeccaLog("Alpecca", line);
    const nextActions = Array.isArray(data?.next_actions) ? data.next_actions.slice(0, 2) : [];
    nextActions.forEach((action: string) => appendAlpeccaLog("System", `Fix: ${String(action)}`));
    showAlpeccaProfileLine(line, "talking", "home");
    showMessage(line, 5.5);
    return data;
  } catch {
    const line = "Doctor check could not reach the Alpecca core status route.";
    appendAlpeccaLog("System", line);
    showAlpeccaProfileLine(line, "listening", "home");
    showMessage(line, 4.5);
    return null;
  }
}

async function runAlpeccaRuntimeSelfReview() {
  alpeccaChat.classList.remove("hidden");
  focusAlpecca(3.2, "idleDown");
  appendAlpeccaLog("System", "Running Alpecca runtime and behavior self-review.");
  setAlpeccaActivity("Alpecca is reviewing her runtime and behavior evidence.", "think", 3.8);
  showAlpeccaProfileLine("Reviewing runtime health and behavior evidence...", "thinking", "self");
  try {
    const response = await alpeccaBackendFetch(alpeccaUrlWithParams(`${alpeccaAiBaseUrl}/cognition/self-review`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    if (!response.ok) throw new Error(`self review ${response.status}`);
    const data = await response.json();
    let behaviorData: any = null;
    try {
      const behaviorResponse = await alpeccaBackendFetch(alpeccaUrlWithParams(`${alpeccaAiBaseUrl}/cognition/behavior-review`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      if (behaviorResponse.ok) behaviorData = await behaviorResponse.json();
    } catch {
      behaviorData = null;
    }
    const review = data.review || {};
    const behaviorReview = behaviorData?.review || {};
    const reviewed = Number(review.reviewed || 0);
    const proposals = Number(review.proposal_count || 0);
    const reused = Number(review.evaluation_reused_count || 0);
    const firstProposal = Array.isArray(review.proposals) && review.proposals[0]?.action
      ? String(review.proposals[0].action)
      : "";
    const behaviorProposal = behaviorReview.proposal?.action ? String(behaviorReview.proposal.action) : "";
    const behaviorReused = behaviorReview.evaluation_reused ? " Existing behavior evidence reused." : " Behavior evidence recorded.";
    const line = behaviorProposal
      ? `I reviewed runtime health and one behavior lesson. ${behaviorProposal} is now evidence-backed.${behaviorReused}`
      : proposals
      ? `I reviewed ${reviewed} runtime gap${reviewed === 1 ? "" : "s"} and kept ${proposals} improvement proposal${proposals === 1 ? "" : "s"} current. ${reused} evidence item${reused === 1 ? "" : "s"} reused.`
      : `I reviewed runtime health. No new bounded improvement proposals were needed.`;
    appendAlpeccaLog("Alpecca", line);
    if (firstProposal) appendAlpeccaLog("System", `Improvement: ${firstProposal}`);
    if (behaviorProposal) appendAlpeccaLog("System", `Behavior review: ${behaviorProposal}`);
    showAlpeccaProfileLine(line, proposals ? "thinking" : "talking", "self");
    showMessage(line, 5);
    if (proposals || behaviorProposal) pulseAlpeccaImprovementQueue(4.2);
    return behaviorData ? { ...data, behavior: behaviorData.review } : data;
  } catch {
    const line = "I could not run self-review right now.";
    appendAlpeccaLog("System", line);
    showAlpeccaProfileLine(line, "listening", "self");
    showMessage(line, 4.5);
    return null;
  }
}

function summarizeAlpeccaImprovementQueue(data: any) {
  const summary = data?.summary || {};
  const proposals = Array.isArray(data?.proposals) ? data.proposals : [];
  const latest = summary.latest || proposals[0] || null;
  const latestEval = summary.latest_evaluation || (Array.isArray(data?.evaluations) ? data.evaluations[0] : null);
  const openCount = Number(summary.recent_open ?? summary.open ?? proposals.filter((proposal: any) => {
    const status = String(proposal?.status || "noticed");
    return !["accepted", "rejected"].includes(status);
  }).length);
  if (!latest) return "My improvement queue is clear right now. I have no open proposals waiting for evidence.";
  const status = String(latest.status || "noticed");
  const action = String(latest.action || "unnamed improvement");
  const approval = String(latest.approval || "ask_first").replace(/_/g, " ");
  const evidence = latestEval?.outcome || latestEval?.evidence || latest.evidence || latest.reason || "";
  const evidenceText = evidence ? ` Evidence: ${String(evidence).slice(0, 130)}` : "";
  return `Improvement queue: ${openCount} recent open proposal${openCount === 1 ? "" : "s"}. Latest is ${status}: ${action}. Approval: ${approval}.${evidenceText}`;
}

async function inspectAlpeccaImprovementQueue() {
  alpeccaChat.classList.remove("hidden");
  focusAlpecca(3.2, "idleDown");
  appendAlpeccaLog("System", "Opening Alpecca improvement queue.");
  setAlpeccaActivity("Alpecca is checking her improvement queue.", "think", 3.6);
  showAlpeccaProfileLine("Reviewing noticed issues, evidence, and next approvals...", "thinking", "studio");
  try {
    const compactResponse = await alpeccaBackendFetch(alpeccaUrlWithParams(`${alpeccaAiBaseUrl}/cognition/proposals/compact`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    const response = compactResponse.ok
      ? compactResponse
      : await alpeccaBackendFetch(alpeccaUrlWithParams(`${alpeccaAiBaseUrl}/cognition/proposals`));
    if (!response.ok) throw new Error(`proposal queue ${response.status}`);
    const data = await response.json();
    const line = summarizeAlpeccaImprovementQueue(data);
    appendAlpeccaLog("Alpecca", line);
    const compactClosed = Number(data?.compact?.closed || 0);
    if (compactClosed) appendAlpeccaLog("System", `Queue cleaned: ${compactClosed} duplicate card${compactClosed === 1 ? "" : "s"} superseded.`);
    const proposals = Array.isArray(data?.proposals) ? data.proposals.slice(0, 3) : [];
    proposals.forEach((proposal: any) => {
      const status = String(proposal?.status || "noticed");
      const action = String(proposal?.action || "proposal");
      appendAlpeccaLog("System", `Queue: ${status}: ${action}`);
    });
    showAlpeccaProfileLine(line, "talking", "studio");
    showMessage(line, 5.5);
    pulseAlpeccaImprovementQueue(proposals.length ? 4.2 : 2.2);
    return data;
  } catch {
    const line = "I could not open my improvement queue right now.";
    appendAlpeccaLog("System", line);
    showAlpeccaProfileLine(line, "listening", "studio");
    showMessage(line, 4.5);
    return null;
  }
}

// ---------------------------------------------------------------------------
// Workshop panel — the visible, evidence-backed, approval-gated improvement
// queue the handoff asked for. It is the in-app surface of the self-improvement
// loop: every card shows its action, evidence, the test it is under, its status,
// and the approval it needs. Alpecca proposes; the person decides. Nothing here
// edits code or acts autonomously — accepting only records the person's
// decision, and a never-auto card is approved as a plan only.
// ---------------------------------------------------------------------------

let workshopBusy = false;
let workshopTrialStatusSequence = 0;
let workshopProposalData: any = null;
let workshopBehaviorCandidate: any = null;

const WORKSHOP_STATUS_LABEL: Record<string, string> = {
  noticed: "Noticed",
  planned: "Planned",
  testing: "Testing",
  accepted: "Accepted",
  rejected: "Rejected",
  superseded: "Superseded",
};
const WORKSHOP_OPEN_STATUSES = new Set(["noticed", "planned", "testing"]);

// Disable controls while a decision is in flight, but never trap the person —
// the close button stays live so the panel can always be dismissed.
function setWorkshopBusy(busy: boolean) {
  alpeccaWorkshop.querySelectorAll<HTMLButtonElement>("button").forEach((button) => {
    if (button.hasAttribute("data-workshop-close")) return;
    button.disabled = busy;
  });
}

// Evaluations arrive newest-first, so the first one seen per proposal is its
// latest — that is the evidence/test/outcome the card should surface.
function latestEvaluationByProposal(evaluations: any[]): Map<number, any> {
  const map = new Map<number, any>();
  for (const ev of Array.isArray(evaluations) ? evaluations : []) {
    const pid = Number(ev?.proposal_id || 0);
    if (pid && !map.has(pid)) map.set(pid, ev);
  }
  return map;
}

// Build one proposal card. Open cards carry the full lifecycle controls; closed
// decisions (accepted/rejected) render muted with a single Reopen affordance.
function workshopCardHtml(proposal: any, evals: Map<number, any>): string {
  const id = Number(proposal?.id || 0);
  const status = String(proposal?.status || "noticed");
  const approval = String(proposal?.approval || "ask_first");
  const risk = String(proposal?.risk || "low");
  const action = escapeHudText(String(proposal?.action || "Untitled proposal"));
  const reason = escapeHudText(String(proposal?.reason || ""));
  const evidence = escapeHudText(String(proposal?.evidence || ""));
  const result = escapeHudText(String(proposal?.result || ""));
  const ev = evals.get(id);
  const test = ev?.test ? escapeHudText(String(ev.test)) : "";
  const outcome = ev?.outcome ? escapeHudText(String(ev.outcome)) : "";
  const isOpen = WORKSHOP_OPEN_STATUSES.has(status);
  const needsApproval = approval !== "automatic" || risk !== "low";
  const approvalLabel = approval.replace(/_/g, " ");

  const controls = isOpen
    ? `<div class="wc-controls">
        <button type="button" data-wc-id="${id}" data-wc-act="planned"${status === "planned" ? " disabled" : ""}>Plan</button>
        <button type="button" data-wc-id="${id}" data-wc-act="testing"${status === "testing" ? " disabled" : ""}>Mark Tested</button>
        <button type="button" class="wc-accept" data-wc-id="${id}" data-wc-act="accepted">${needsApproval ? "Accept plan" : "Accept"}</button>
        <button type="button" class="wc-reject" data-wc-id="${id}" data-wc-act="rejected">Reject</button>
      </div>`
    : `<div class="wc-controls wc-controls-closed">
        <span class="wc-closed-note">${result ? `Closed: ${result}` : "Closed decision."}</span>
        <button type="button" data-wc-id="${id}" data-wc-act="testing">Reopen</button>
      </div>`;

  const candidate = workshopBehaviorCandidate;
  const candidateMatches = Number(candidate?.proposal_id || 0) === id;
  const candidateState = String(candidate?.state || "");
  const trial = candidate?.trial && typeof candidate.trial === "object" ? candidate.trial : null;
  const trialState = String(trial?.state || "");
  let trialControls = "";
  if (candidateMatches && candidateState === "ready_for_registration") {
    trialControls = `<div class="wc-controls"><button type="button" data-wc-id="${id}" data-wc-trial-act="register">Register trial</button></div>`;
  } else if (candidateMatches && candidateState === "registered" && trial) {
    const trialId = Number(trial?.id || 0);
    if (trialId > 0 && trialState === "registered") {
      trialControls = `<div class="wc-controls"><button type="button" data-wc-id="${id}" data-wc-trial-id="${trialId}" data-wc-trial-act="approve">Approve trial</button></div>`;
    } else if (trialId > 0 && trialState === "approved") {
      trialControls = `<div class="wc-controls"><button type="button" data-wc-id="${id}" data-wc-trial-id="${trialId}" data-wc-trial-act="start">Start trial</button></div>`;
    } else if (trialState === "running") {
      trialControls = `<div class="wc-controls wc-controls-closed"><span class="wc-closed-note">Bounded trial running.</span></div>`;
    }
  }

  return `<div class="workshop-card wc-card-${status}" data-proposal-id="${id}">
    <div class="wc-top">
      <span class="wc-action">${action}</span>
      <span class="wc-badges">
        <span class="wc-badge wc-badge-${status}">${WORKSHOP_STATUS_LABEL[status] || status}</span>
        <span class="wc-badge wc-risk-${risk}">${risk} risk</span>
        <span class="wc-badge wc-badge-approval">${approvalLabel}</span>
      </span>
    </div>
    ${reason ? `<p class="wc-reason">${reason}</p>` : ""}
    ${evidence ? `<div class="wc-line"><b>Evidence</b> ${evidence}</div>` : ""}
    ${test ? `<div class="wc-line"><b>Test</b> ${test}</div>` : ""}
    ${outcome ? `<div class="wc-line"><b>Outcome</b> ${outcome}</div>` : ""}
    ${controls}
    ${trialControls}
  </div>`;
}

function renderWorkshopProposals(data: any) {
  const proposals = Array.isArray(data?.proposals) ? data.proposals : [];
  const summary = data?.summary || {};
  const evals = latestEvaluationByProposal(data?.evaluations || []);
  const openCount = Number(summary.recent_open ?? summary.open ?? 0);
  const total = Number(summary.recent_total ?? summary.total ?? proposals.length);
  workshopSummary.textContent = proposals.length
    ? `${openCount} open · ${total} tracked`
    : "Queue clear";

  if (!proposals.length) {
    workshopList.innerHTML = `<div class="workshop-empty">Nothing in the queue yet. Run a review to let Alpecca surface a bounded improvement.</div>`;
    return;
  }

  // Partition so the actionable items lead. Superseded cards are auto-closed
  // duplicates — pure noise — so they collapse to a single count line instead of
  // burying the open work under dozens of muted "Reopen" rows.
  const open = proposals.filter((p: any) => WORKSHOP_OPEN_STATUSES.has(String(p?.status || "")));
  const decided = proposals.filter((p: any) => {
    const status = String(p?.status || "");
    return status === "accepted" || status === "rejected";
  });
  const supersededCount = proposals.filter((p: any) => String(p?.status || "") === "superseded").length;

  const sections: string[] = [];
  if (open.length) {
    sections.push(open.map((p: any) => workshopCardHtml(p, evals)).join(""));
    // The list is the newest 25 by id; if the true open count is larger, some
    // open items are off-window. Compacting duplicate cards brings them back.
    if (openCount > open.length) {
      sections.push(`<div class="workshop-note">Showing ${open.length} of ${openCount} open · run Compact to clear duplicates and surface the rest.</div>`);
    }
  } else {
    sections.push(`<div class="workshop-empty">No open proposals — the queue is clear. Run a review to surface a bounded improvement.</div>`);
  }
  if (decided.length) {
    sections.push(`<div class="workshop-divider">Past decisions</div>`);
    sections.push(decided.map((p: any) => workshopCardHtml(p, evals)).join(""));
  }
  if (supersededCount) {
    sections.push(`<div class="workshop-note">${supersededCount} superseded duplicate${supersededCount === 1 ? "" : "s"} hidden (auto-closed, history preserved).</div>`);
  }

  workshopList.innerHTML = sections.join("");
}

async function loadAlpeccaWorkshop() {
  try {
    const response = await alpeccaBackendFetch(alpeccaUrlWithParams(`${alpeccaAiBaseUrl}/cognition/proposals`));
    if (!response.ok) throw new Error(`proposal queue ${response.status}`);
    const data = await response.json();
    workshopProposalData = data;
    renderWorkshopProposals(data);
    return data;
  } catch {
    workshopProposalData = null;
    workshopSummary.textContent = "Queue unavailable";
    workshopList.innerHTML = `<div class="workshop-empty">The improvement queue is unavailable right now. Check that the Alpecca core is running.</div>`;
    return null;
  }
}

async function loadWorkshopTrialStatus() {
  const sequence = ++workshopTrialStatusSequence;
  let status = "Behavior review: unavailable";
  workshopTrialStatus.textContent = "Behavior review: loading...";
  workshopReviewDecision.replaceChildren();
  workshopReviewDecision.classList.add("hidden");
  try {
    const response = await alpeccaBackendFetch(
      alpeccaUrlWithParams(`${alpeccaAiBaseUrl}/behavior-trials/status`),
      { method: "GET", cache: "no-store", signal: AbortSignal.timeout(5000) },
    );
    if (response.status === 401) {
      status = "Behavior review: sign-in required";
    } else if (response.status === 403) {
      status = "Behavior review: creator access required";
    } else if (response.status === 503) {
      status = "Behavior review: recovery pending";
    } else if (response.status === 200) {
      const data = await response.json() as {
        active_trial?: unknown;
        outcome_evidence?: unknown;
        review_settlements?: unknown;
        review_settlements_available?: unknown;
        review_decisions?: unknown;
        review_decisions_available?: unknown;
        profile_decisions?: unknown;
        profile_decisions_available?: unknown;
        active_profile?: unknown;
        cycle_baseline?: unknown;
        registration_candidate?: unknown;
        registration_candidate_available?: unknown;
      };
      const activeTrial = data?.active_trial;
      let baselineText = "baseline observation awaiting settled deliveries";
      const evidence = data?.outcome_evidence;
      if (
        (data?.cycle_baseline && typeof data.cycle_baseline === "object")
        || (evidence && typeof evidence === "object")
      ) {
        const baseline = data?.cycle_baseline && typeof data.cycle_baseline === "object"
          ? data.cycle_baseline
          : (evidence as { baseline?: unknown }).baseline;
        if (baseline && typeof baseline === "object") {
          const values = baseline as { completed?: unknown; qualified_responses?: unknown; rate?: unknown };
          const completed = Number.isInteger(values.completed) && Number(values.completed) >= 0
            ? Number(values.completed)
            : 0;
          const qualified = Number.isInteger(values.qualified_responses) && Number(values.qualified_responses) >= 0
            ? Number(values.qualified_responses)
            : 0;
          const rate = typeof values.rate === "number" && Number.isFinite(values.rate)
            ? Math.max(0, Math.min(1, values.rate))
            : null;
          if (completed > 0 && rate !== null) {
            baselineText = `baseline ${qualified}/${completed} qualified responses (${Math.round(rate * 100)}%)`;
          }
        }
      }
      let reviewText = "no settled trial review";
      let latestReview: {
        trialId: number;
        status: string;
        outcome: string;
        retentionEligible: boolean;
        preimageValue: number | null;
        trialValue: number | null;
        exposureSeconds: number | null;
        minSamples: number | null;
      } | null = null;
      if (data?.review_settlements_available === false) {
        reviewText = "settled review history unavailable";
      } else if (Array.isArray(data?.review_settlements)) {
        const latest = data.review_settlements.find((item) => item && typeof item === "object") as {
          trial_id?: unknown;
          status?: unknown;
          outcome?: unknown;
          creator_retention_eligible?: unknown;
          profile?: unknown;
        } | undefined;
        const latestTrialId = Number(latest?.trial_id || 0);
        const latestStatus = typeof latest?.status === "string" ? latest.status : "";
        if (latestTrialId > 0 && Number.isInteger(latestTrialId) && latestStatus) {
          const profile = latest?.profile && typeof latest.profile === "object"
            ? latest.profile as {
                preimage_value?: unknown;
                trial_value?: unknown;
                exposure_seconds?: unknown;
                min_samples?: unknown;
              }
            : null;
          const finiteOrNull = (value: unknown) => {
            const number = Number(value);
            return Number.isFinite(number) ? number : null;
          };
          latestReview = {
            trialId: latestTrialId,
            status: latestStatus,
            outcome: typeof latest?.outcome === "string" ? latest.outcome : "inconclusive",
            retentionEligible: latest?.creator_retention_eligible === true,
            preimageValue: finiteOrNull(profile?.preimage_value),
            trialValue: finiteOrNull(profile?.trial_value),
            exposureSeconds: finiteOrNull(profile?.exposure_seconds),
            minSamples: finiteOrNull(profile?.min_samples),
          };
          if (latestStatus === "ready_for_creator_review") {
            reviewText = `trial #${latestTrialId} is ready for creator review`;
          } else if (latestStatus === "inconclusive_insufficient_samples") {
            reviewText = `trial #${latestTrialId} concluded with insufficient evidence`;
          }
        }
      }
      if (latestReview) {
        const matchingDecision = Array.isArray(data?.profile_decisions)
          ? data.profile_decisions.find((item) => {
              if (!item || typeof item !== "object") return false;
              const value = item as { trial_id?: unknown; decision?: unknown };
              return Number(value.trial_id || 0) === latestReview?.trialId;
            })
          : null;
        if (matchingDecision) {
          const decision = String((matchingDecision as { decision?: unknown }).decision || "");
          const retained = decision === "retain_trial_value";
          reviewText = retained
            ? `trial #${latestReview.trialId} completed; trial value retained`
            : `trial #${latestReview.trialId} completed; baseline kept`;
          workshopReviewDecision.textContent = retained
            ? "Cycle complete. The reviewed trial value is now the active profile."
            : "Cycle complete. The pre-trial profile remains active.";
          workshopReviewDecision.classList.remove("hidden");
        } else if (data?.profile_decisions_available !== false) {
          const retainButton = latestReview.retentionEligible
            ? `<button type="button" data-wc-review-trial-id="${latestReview.trialId}" data-wc-review-act="retain-trial-value">Retain trial value</button>`
            : "";
          const valueDetail = latestReview.preimageValue !== null && latestReview.trialValue !== null
            ? ` Trial ${Math.round(latestReview.trialValue * 100)}% vs baseline ${Math.round(latestReview.preimageValue * 100)}%.`
            : "";
          const exposureDetail = latestReview.exposureSeconds !== null && latestReview.minSamples !== null
            ? ` ${Math.round(latestReview.exposureSeconds / 60)} min, minimum ${latestReview.minSamples} outcomes.`
            : "";
          workshopReviewDecision.innerHTML = `<span>Frozen result: ${escapeHudText(latestReview.outcome)}.${valueDetail}${exposureDetail}</span>${retainButton}<button type="button" data-wc-review-trial-id="${latestReview.trialId}" data-wc-review-act="revert-to-baseline">Keep baseline</button>`;
          workshopReviewDecision.classList.remove("hidden");
        } else {
          reviewText += "; profile decision status unavailable";
        }
      }
      status = `Behavior review: ${baselineText}. ${reviewText}.`;
      const activeProfile = data?.active_profile;
      if (activeProfile && typeof activeProfile === "object") {
        const value = Number((activeProfile as { value?: unknown }).value);
        if (Number.isFinite(value)) {
          status += ` Active chatter profile: ${Math.round(value * 100)}%.`;
        }
      }
      if (activeTrial === null) {
        status += " No active trial.";
      } else if (activeTrial && typeof activeTrial === "object") {
        const trial = activeTrial as {
          id?: unknown;
          state?: unknown;
          parameter?: unknown;
          creator_binding_present?: unknown;
        };
        if (
          (trial.state === "approved" || trial.state === "running") &&
          trial.parameter === "chatter_chance"
        ) {
          status += trial.creator_binding_present === true
            ? ` Active chatter chance trial: ${trial.state}.`
            : " Active trial approval is not bound.";
          const activeTrialId = Number(trial.id || 0);
          if (
            trial.state === "running"
            && Number.isInteger(activeTrialId)
            && activeTrialId > 0
          ) {
            workshopReviewDecision.innerHTML = `<span>Trial #${activeTrialId} is running.</span><button type="button" data-wc-trial-id="${activeTrialId}" data-wc-trial-act="abort">Abort trial</button>`;
            workshopReviewDecision.classList.remove("hidden");
          }
        }
      }
      const candidate = data?.registration_candidate;
      if (candidate && typeof candidate === "object") {
        const candidateRecord = candidate as { proposal_id?: unknown; state?: unknown };
        const proposalId = Number(candidateRecord.proposal_id || 0);
        const candidateState = String(candidateRecord.state || "");
        workshopBehaviorCandidate = candidateRecord;
        if (proposalId > 0 && candidateState === "ready_for_registration") {
          status += " A plan is ready for creator registration.";
        } else if (proposalId > 0 && candidateState === "pending_creator_plan") {
          status += " A behavior candidate is awaiting plan acceptance.";
        } else if (proposalId > 0 && candidateState === "registered") {
          status += " A registered trial is awaiting its separate decision.";
        }
      } else {
        workshopBehaviorCandidate = null;
        if (data?.registration_candidate_available === false) {
          status += " Candidate status unavailable.";
        }
      }
    }
  } catch {
    // Status is advisory only; failures must not imply that no trial is active.
  }
  if (sequence === workshopTrialStatusSequence) {
    workshopTrialStatus.textContent = status;
    if (workshopProposalData) renderWorkshopProposals(workshopProposalData);
  }
}

function openAlpeccaWorkshop() {
  alpeccaWorkshop.classList.remove("hidden");
  workshopBehaviorCandidate = null;
  workshopSummary.textContent = "Loading...";
  workshopList.innerHTML = `<div class="workshop-empty">Loading the queue...</div>`;
  appendAlpeccaLog("System", "Opening the improvement Workshop.");
  pulseAlpeccaImprovementQueue(3.4);
  void loadAlpeccaWorkshop();
  void loadWorkshopTrialStatus();
}

function closeAlpeccaWorkshop() {
  workshopTrialStatusSequence += 1;
  workshopBehaviorCandidate = null;
  workshopTrialStatus.textContent = "";
  workshopReviewDecision.replaceChildren();
  workshopReviewDecision.classList.add("hidden");
  alpeccaWorkshop.classList.add("hidden");
}

async function workshopBehaviorTrialAction(proposalId: number, action: string, trialId = 0) {
  if (workshopBusy) return;
  let path = "";
  let confirmation = "";
  if (action === "register") {
    if (!proposalId) return;
    path = `/behavior-trials/proposals/${proposalId}/register`;
    confirmation = "Register this sealed proposal as a trial? This does not change Alpecca's behavior. Approval and start remain separate decisions.";
  } else if (action === "approve" && trialId > 0) {
    path = `/behavior-trials/${trialId}/approve`;
    confirmation = "Approve this registered trial? This records approval only and does not start it.";
  } else if (action === "start" && trialId > 0) {
    path = `/behavior-trials/${trialId}/start`;
    confirmation = "Start this time-bounded behavior trial? It will automatically roll back after its planned exposure.";
  } else if (action === "abort" && trialId > 0) {
    path = `/behavior-trials/${trialId}/abort`;
    confirmation = "Abort this trial now? The active override will be restored to its baseline and the result will close as inconclusive.";
  } else {
    return;
  }
  if (!window.confirm(confirmation)) return;
  workshopBusy = true;
  setWorkshopBusy(true);
  try {
    const response = await alpeccaBackendFetch(alpeccaUrlWithParams(`${alpeccaAiBaseUrl}${path}`), {
      method: "POST",
      cache: "no-store",
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => null);
      throw new Error(String(detail?.detail || `behavior trial ${response.status}`));
    }
    appendAlpeccaLog("System", action === "register"
      ? `Registered behavior trial from proposal #${proposalId}; no behavior changed.`
      : action === "approve"
        ? `Approved behavior trial #${trialId}; it has not started.`
        : action === "start"
          ? `Started bounded behavior trial #${trialId}.`
          : `Aborted behavior trial #${trialId}; the baseline was restored.`);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Behavior trial action failed.";
    appendAlpeccaLog("System", message);
  } finally {
    workshopBusy = false;
    setWorkshopBusy(false);
    await Promise.all([loadAlpeccaWorkshop(), loadWorkshopTrialStatus()]);
  }
}

async function workshopReviewDecisionAction(trialId: number, decision: string) {
  if (workshopBusy || !Number.isInteger(trialId) || trialId <= 0) return;
  if (decision !== "retain-trial-value" && decision !== "revert-to-baseline") return;
  const decisionName = decision === "retain-trial-value"
    ? "retain_trial_value"
    : "revert_to_baseline";
  const confirmation = decision === "retain-trial-value"
    ? "Retain this evidence-qualified trial value as Alpecca's active chatter profile? The decision is durable and becomes the baseline for the next bounded cycle."
    : "Keep the pre-trial chatter profile and close this cycle? A fresh baseline epoch will begin without retaining the trial value.";
  if (!window.confirm(confirmation)) return;
  workshopBusy = true;
  setWorkshopBusy(true);
  try {
    const response = await alpeccaBackendFetch(
      alpeccaUrlWithParams(`${alpeccaAiBaseUrl}/behavior-trials/${trialId}/review/decision/${decisionName}`),
      { method: "POST", cache: "no-store" },
    );
    if (!response.ok) {
      const detail = await response.json().catch(() => null);
      throw new Error(String(detail?.detail || `review acknowledgement ${response.status}`));
    }
    appendAlpeccaLog(
      "System",
      decision === "retain-trial-value"
        ? `Completed behavior trial #${trialId}; the qualified trial value is active.`
        : `Completed behavior trial #${trialId}; the baseline remains active.`,
    );
  } catch (error) {
    const message = error instanceof Error ? error.message : "Review acknowledgement failed.";
    appendAlpeccaLog("System", message);
  } finally {
    workshopBusy = false;
    setWorkshopBusy(false);
    await Promise.all([loadAlpeccaWorkshop(), loadWorkshopTrialStatus()]);
  }
}

async function workshopProposalDecision(proposalId: number, status: string) {
  if (workshopBusy || !proposalId) return;
  let approvedByUser = false;
  let result = "";
  if (status === "accepted") {
    const ok = window.confirm(
      "Accept this plan with your approval?\n\n" +
      "This records your explicit approval. A never-auto card is approved as a plan only — " +
      "Alpecca will not act on it unassisted, and makes no autonomous code edits."
    );
    if (!ok) return;
    approvedByUser = true;
    result = "Accepted with user approval from the Workshop.";
  } else if (status === "rejected") {
    if (!window.confirm("Reject and close this proposal?")) return;
    result = "Rejected from the Workshop.";
  } else if (status === "testing") {
    result = "Moved to testing from the Workshop.";
  } else if (status === "planned") {
    result = "Planned from the Workshop.";
  }
  workshopBusy = true;
  setWorkshopBusy(true);
  try {
    const response = await alpeccaBackendFetch(alpeccaUrlWithParams(`${alpeccaAiBaseUrl}/cognition/proposals/${proposalId}`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status, result, approved_by_user: approvedByUser }),
    });
    if (response.status === 403) {
      const detail = await response.json().catch(() => null);
      window.alert(`Could not accept: ${detail?.detail || "explicit user approval is required"}`);
      return;
    }
    if (!response.ok) throw new Error(`proposal update ${response.status}`);
    appendAlpeccaLog("System", `Queue: proposal #${proposalId} → ${status}.`);
    pulseAlpeccaImprovementQueue(3.6);
  } catch {
    appendAlpeccaLog("System", `Could not move proposal #${proposalId} to ${status}.`);
  } finally {
    workshopBusy = false;
    setWorkshopBusy(false);
    await Promise.all([loadAlpeccaWorkshop(), loadWorkshopTrialStatus()]);
  }
}

async function workshopRunReview() {
  if (workshopBusy) return;
  workshopBusy = true;
  setWorkshopBusy(true);
  workshopSummary.textContent = "Running self-review...";
  try {
    await runAlpeccaRuntimeSelfReview();
  } finally {
    workshopBusy = false;
    setWorkshopBusy(false);
    await Promise.all([loadAlpeccaWorkshop(), loadWorkshopTrialStatus()]);
  }
}

async function workshopCompact() {
  if (workshopBusy) return;
  workshopBusy = true;
  setWorkshopBusy(true);
  try {
    const response = await alpeccaBackendFetch(alpeccaUrlWithParams(`${alpeccaAiBaseUrl}/cognition/proposals/compact`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    if (response.ok) {
      const data = await response.json();
      const closed = Number(data?.compact?.closed || 0);
      appendAlpeccaLog("System", closed
        ? `Queue cleaned: ${closed} duplicate card${closed === 1 ? "" : "s"} superseded.`
        : "Queue already compact.");
      renderWorkshopProposals(data);
    }
  } catch {
    appendAlpeccaLog("System", "Could not compact the queue.");
  } finally {
    workshopBusy = false;
    setWorkshopBusy(false);
  }
}

async function workshopExportHandoff() {
  if (workshopBusy) return;
  workshopBusy = true;
  setWorkshopBusy(true);
  workshopSummary.textContent = "Preparing handoff...";
  try {
    const response = await alpeccaBackendFetch(alpeccaUrlWithParams(`${alpeccaAiBaseUrl}/cognition/proposals/handoff?limit=8`));
    if (!response.ok) throw new Error(`handoff ${response.status}`);
    const data = await response.json();
    const markdown = String(data?.markdown || "");
    const count = Number(data?.proposal_count || 0);
    if (markdown && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(markdown);
      appendAlpeccaLog("System", "Copied Alpecca improvement handoff to clipboard.");
    } else if (markdown) {
      appendAlpeccaLog("System", "Alpecca improvement handoff is ready, but clipboard access is unavailable.");
    }
    const line = count
      ? `I prepared a bounded handoff with ${count} open improvement proposal${count === 1 ? "" : "s"} for Codex, Claude, or ChatGPT.`
      : "I prepared a handoff, but my queue is empty. Run a review first if you want external help.";
    showAlpeccaProfileLine(line, "thinking", "self");
    showMessage(line, 4.4);
    workshopSummary.textContent = count ? `${count} proposal${count === 1 ? "" : "s"} exported` : "Handoff ready";
  } catch {
    appendAlpeccaLog("System", "Could not prepare the improvement handoff.");
    workshopSummary.textContent = "Handoff unavailable";
  } finally {
    workshopBusy = false;
    setWorkshopBusy(false);
  }
}

function alpeccaFeatureToolUrl(feature: AlpeccaSourceFeature, room: OfficeRoom) {
  if (!feature.toolPath) return "";
  const base = `${alpeccaAiBaseUrl}${feature.toolPath}`;
  if (feature.id === "memory") {
    const memory = environmentMemoryForRoom(room.id);
    const query = memory.lastQuestion || memory.lastSeen || `${room.name} ${room.purpose}`;
    return alpeccaUrlWithParams(`${base}?q=${encodeURIComponent(query)}&limit=3`);
  }
  return alpeccaUrlWithParams(base);
}

function summarizeAlpeccaToolResult(feature: AlpeccaSourceFeature, data: any) {
  if (feature.id === "self") {
    const mood = String(data?.mood || data?.state?.mood || alpeccaAiMood || "current");
    const narration = String(data?.narration || data?.reason || "").trim();
    return narration ? `Self report (${mood}): ${narration.slice(0, 180)}` : `Self report: mood ${mood}.`;
  }
  if (feature.id === "memory") {
    const results = Array.isArray(data?.results) ? data.results : [];
    const first = results[0]?.content ? String(results[0].content) : "";
    return first ? `Memory recall: ${first.slice(0, 190)}` : `Memory recall found ${Number(data?.count || 0)} stored memories, but no close match.`;
  }
  if (feature.id === "journal") {
    const question = Array.isArray(data?.open_questions) && data.open_questions[0]?.question
      ? String(data.open_questions[0].question)
      : "";
    const recent = Array.isArray(data?.recent) && data.recent[0]?.content ? String(data.recent[0].content) : "";
    return question ? `Journal question: ${question.slice(0, 180)}` : recent ? `Journal note: ${recent.slice(0, 180)}` : "Journal is quiet right now.";
  }
  if (feature.id === "studio") {
    const latest = Array.isArray(data?.proposals) && data.proposals[0]?.action ? String(data.proposals[0].action) : "";
    const desire = Array.isArray(data?.desires) && data.desires[0]?.text ? String(data.desires[0].text) : "";
    return latest ? `Workshop proposal: ${latest.slice(0, 180)}` : desire ? `Workshop desire: ${desire.slice(0, 180)}` : "Workshop has no urgent proposal yet.";
  }
  if (feature.id === "home") {
    const location = String(data?.location || data?.current_room || data?.room || "");
    const reason = String(data?.why || data?.reason || data?.summary || "").trim();
    return `Home state: ${location || "inside the HQ"}${reason ? ` - ${reason.slice(0, 160)}` : ""}.`;
  }
  if (feature.id === "soul") {
    const focus = data?.focus || data?.intention || {};
    const name = String(focus?.name || focus?.directive || focus?.intent || "current intention");
    const reason = String(focus?.reason || focus?.why || "").trim();
    return `Soul focus: ${name}${reason ? ` - ${reason.slice(0, 160)}` : ""}.`;
  }
  return `${feature.room}: tool state read.`;
}

async function runAlpeccaFeatureToolBridge(featureId: string, room: OfficeRoom, visible = true) {
  const feature = alpeccaSourceFeatures[featureId];
  if (!feature?.toolPath || alpeccaAiStatus !== "live") return null;
  if (!visible && alpeccaPlayerChatQuietTimer > 0) return null;
  try {
    const response = await alpeccaBackendFetch(alpeccaFeatureToolUrl(feature, room));
    if (!response.ok) throw new Error(`tool ${feature.id} ${response.status}`);
    const data = await response.json();
    const summary = summarizeAlpeccaToolResult(feature, data);
    pulseAlpeccaSourceTerminal(feature.id, 2.8, true);
    pulseAlpeccaSourceDashboard(feature.id, 2.6);
    if (visible) {
      appendAlpeccaLog("System", `${feature.room} tool: ${summary}`);
      showAlpeccaProfileLine(summary, "thinking", feature.id);
      showMessage(summary, 4.4);
    }
    void alpeccaBackendFetch(alpeccaUrlWithParams(`${alpeccaAiBaseUrl}/cognition/observe`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source: "house-tool-bridge",
        room: room.name,
        content: `${feature.room} tool bridge read ${feature.toolPath}: ${summary}`,
        confidence: 0.9,
        novelty: 0.52,
        metadata: {
          feature: feature.id,
          toolPath: feature.toolPath,
          roomId: room.id,
        },
      }),
    }).catch(() => undefined);
    return { feature, summary, data };
  } catch {
    if (visible) appendAlpeccaLog("System", `${feature.room} tool bridge is unavailable.`);
    return null;
  }
}

function runAlpeccaFeature(featureId: string) {
  const feature = alpeccaSourceFeatures[featureId];
  if (!feature) return;

  alpeccaActiveProfileFeature = feature.id;
  alpeccaChat.classList.remove("hidden");
  showAlpeccaProfileLine(`${feature.room}: ${feature.prompt}`, "thinking", feature.id);
  appendAlpeccaLog("System", `${feature.room}: ${feature.label}`);
  setAlpeccaActivity(`Alpecca is checking ${feature.room}.`, "think");
  pulseAlpeccaSourceTerminal(feature.id, 3.4, false);
  pulseAlpeccaSourceDashboard(feature.id, 3.2);
  const featureRoom = officeRooms.find((room) => room.name === feature.room) ?? currentOfficeRoom();
  const ideaKind = alpeccaIdeaKindForFeature(feature.id);
  createAlpeccaIdeaObject(featureRoom, `${feature.label}: ${feature.prompt}`, ideaKind);
  const featureAnimation: AlpeccaAnimationName =
    feature.id === "studio"
      ? directionalAlpeccaJump(alpeccaToPlayer.copy(camera.position).sub(alpecca.group.position))
      : feature.id === "home"
        ? "point"
        : feature.id === "self"
          ? "kneel"
          : "idleDown";
  const featureAnimationReady = alpecca.animations.has(featureAnimation);
  focusAlpecca(2.8, featureAnimation);
  alpecca.expressiveTimer = featureAnimationReady ? 2 : 7;
  void runAlpeccaFeatureToolBridge(feature.id, featureRoom, true);

  if (alpeccaAiStatus === "live" && alpeccaSocket?.readyState === WebSocket.OPEN) {
    showMessage(`${feature.room}: recording ${feature.label.toLowerCase()} as house context.`, 3.2);
    void alpeccaBackendFetch(alpeccaUrlWithParams(`${alpeccaAiBaseUrl}/cognition/observe`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source: "room-terminal",
        room: feature.room,
        content: `Room terminal request: ${feature.prompt}`,
        confidence: 0.78,
        novelty: 0.45,
        metadata: {
          feature: feature.id,
          label: feature.label,
          context: alpeccaContextPrefix(),
        },
      }),
    }).catch(() => undefined);
    return;
  }

  if (alpeccaAiStatus === "token") {
    showMessage("Alpecca source needs an authorized backend session. Sign in, then try this terminal again.", 5);
    return;
  }

  const fallback = `${feature.room}: ${feature.label}. ${feature.page ? "Source app may answer when live." : "Using local game mode."}`;
  appendAlpeccaLog("Alpecca", fallback);
  showAlpeccaProfileLine(fallback, "talking", feature.id);
  startAlpeccaSpeech(fallback);
  showMessage(`${feature.room} source bridge is offline. ${feature.page ? "Opening the source page may still work if Alpecca is running." : "Using local game mode."}`, 5);
}

const alpeccaTerminalReachDistance = 0.58;
const alpeccaTerminalApproachLeadDistance = 1.15;
const alpeccaTerminalDefaultTiming: AlpeccaTerminalTiming = {
  reachSeconds: 0.56,
  contactSeconds: 0.34,
  retractSeconds: 0.7,
};

function registerAlpeccaTerminalTarget(
  id: string,
  featureId: string,
  roomId: string,
  label: string,
  group: THREE.Group,
  contactLocal: THREE.Vector3,
  attentionLocal: THREE.Vector3,
  hand: AlpeccaTerminalHand = "right",
  timing: AlpeccaTerminalTiming = alpeccaTerminalDefaultTiming,
) {
  group.updateWorldMatrix(true, false);
  const contactNormal = new THREE.Vector3(0, 0, 1).transformDirection(group.matrixWorld).normalize();
  const contact = group.localToWorld(contactLocal.clone());
  const attention = group.localToWorld(attentionLocal.clone());
  const approach = contact.clone().addScaledVector(contactNormal, alpeccaTerminalReachDistance);
  approach.y = 0.04;
  alpeccaTerminalTargets.set(id, {
    id,
    featureId,
    roomId,
    label,
    group,
    approach,
    attention,
    contact,
    contactNormal,
    hand,
    timing: { ...timing },
  });
}

function alpeccaTerminalTargetForPoint(point: AlpeccaExplorePoint) {
  const roomTargets = [...alpeccaTerminalTargets.values()].filter((target) => target.roomId === point.roomId);
  if (!roomTargets.length) return null;
  const assigned = point.featureId
    ? roomTargets.find((target) => target.featureId === point.featureId)
    : null;
  if (assigned) return assigned;
  return roomTargets.reduce((nearest, candidate) => {
    const nearestDistance = nearest.approach.distanceToSquared(point.position);
    const candidateDistance = candidate.approach.distanceToSquared(point.position);
    return candidateDistance < nearestDistance ? candidate : nearest;
  });
}

function addSourceTerminal(featureId: string, pos: THREE.Vector3Tuple, yaw: number) {
  const feature = alpeccaSourceFeatures[featureId];
  if (!feature) return;

  const group = new THREE.Group();
  group.name = `${feature.room} ${feature.id} source terminal`;
  group.position.set(pos[0], 0, pos[2]);
  group.rotation.y = yaw;
  group.scale.setScalar(0.88);
  scene.add(group);

  const accent = new THREE.MeshStandardMaterial({
    color: feature.color,
    emissive: feature.color,
    emissiveIntensity: 0.55,
    roughness: 0.35,
  });
  groupBox(group, [0.96, 0.05, 0.68], [0, 0.025, 0], materials.darkWood);
  for (const x of [-0.31, 0.31]) {
    for (const z of [-0.19, 0.19]) {
      groupBox(group, [0.075, Math.max(0.12, pos[1] - 0.08), 0.075], [x, Math.max(0.12, pos[1] - 0.08) / 2 + 0.05, z], materials.metal);
    }
  }
  groupBox(group, [0.78, 0.12, 0.54], [0, pos[1], 0], materials.metal);
  groupBox(group, [0.58, 0.08, 0.34], [0, pos[1] + 0.1, 0.02], accent);
  groupBox(group, [0.16, 0.32, 0.08], [-0.28, pos[1] + 0.28, -0.12], accent);
  groupBox(group, [0.16, 0.32, 0.08], [0.28, pos[1] + 0.28, -0.12], materials.screen);
  addContactOcclusion(`${feature.room} source terminal contact ao`, [1.1, 0.8], [pos[0], 0.012, pos[2]], 0.16);
  addGroundCable(`${feature.room} source terminal floor cable`, [pos[0], 0.04, pos[2]], [pos[0] - Math.sin(yaw) * 0.48, 0.04, pos[2] - Math.cos(yaw) * 0.48], feature.color);
  const signalMaterial = new THREE.MeshBasicMaterial({
    color: feature.color,
    transparent: true,
    opacity: 0.18,
    depthWrite: false,
    side: THREE.DoubleSide,
  });
  const halo = new THREE.Mesh(new THREE.RingGeometry(0.18, 0.25, 32), signalMaterial);
  halo.name = `${feature.room} source terminal response halo`;
  halo.rotation.x = -Math.PI / 2;
  halo.position.set(0, pos[1] + 0.19, 0.08);
  halo.renderOrder = 7;
  group.add(halo);
  const signalCore = new THREE.Mesh(new THREE.OctahedronGeometry(0.07, 0), signalMaterial);
  signalCore.name = `${feature.room} source terminal response core`;
  signalCore.position.set(0, pos[1] + 0.34, 0.04);
  signalCore.renderOrder = 8;
  group.add(signalCore);

  const light = new THREE.PointLight(feature.color, 0.28, 2.0, 2);
  light.position.set(pos[0], pos[1] + 0.35, pos[2]);
  scene.add(light);
  alpeccaSourceTerminals.set(feature.id, {
    featureId: feature.id,
    group,
    accentMaterial: accent,
    signalMaterial,
    light,
    baseYaw: yaw,
    pulseTimer: 0,
    autonomousTimer: 0,
  });
  const roomId = officeRooms.find((room) => room.name === feature.room)?.id ?? officeRoomAtPosition(pos[0], pos[2]).id;
  registerAlpeccaTerminalTarget(
    `source-${feature.id}`,
    feature.id,
    roomId,
    `${feature.room} ${feature.label}`,
    group,
    new THREE.Vector3(0.28, pos[1] + 0.4, -0.08),
    new THREE.Vector3(0, pos[1] + 0.34, 0.04),
  );

  register({
    id: `source-${feature.id}`,
    label: feature.label,
    root: group,
    range: 1.9,
    type: "momentary",
    onUse: () => {
      runAlpeccaFeature(feature.id);
      return "";
    },
    update: () => {},
  });
}

function pulseAlpeccaSourceTerminal(featureId: string, seconds = 2.6, autonomous = false) {
  const terminal = alpeccaSourceTerminals.get(featureId);
  if (!terminal) return;
  terminal.pulseTimer = Math.max(terminal.pulseTimer, seconds);
  if (autonomous) terminal.autonomousTimer = Math.max(terminal.autonomousTimer, seconds * 0.78);
}

function updateAlpeccaSourceTerminals(dt: number) {
  const now = performance.now();
  for (const terminal of alpeccaSourceTerminals.values()) {
    if (terminal.pulseTimer > 0) terminal.pulseTimer -= dt;
    if (terminal.autonomousTimer > 0) terminal.autonomousTimer -= dt;
    const active = terminal.pulseTimer > 0;
    const autonomous = terminal.autonomousTimer > 0;
    const live = alpeccaAiStatus === "live";
    const pulse = active ? 0.36 + Math.sin(now / 160 + terminal.group.position.x) * 0.08 : live ? 0.2 : 0.08;
    const important = active || autonomous;
    terminal.light.intensity = THREE.MathUtils.damp(terminal.light.intensity, (active ? 0.44 : live ? 0.22 : 0.06) * calmLightMultiplier(important), 7, dt);
    terminal.signalMaterial.opacity = THREE.MathUtils.damp(terminal.signalMaterial.opacity, pulse * calmVisualMultiplier(important), 8, dt);
    terminal.accentMaterial.emissiveIntensity = THREE.MathUtils.damp(
      terminal.accentMaterial.emissiveIntensity,
      (active ? 0.72 : live ? 0.42 : 0.22) * calmLightMultiplier(important),
      7,
      dt,
    );
    terminal.group.rotation.y = THREE.MathUtils.damp(terminal.group.rotation.y, terminal.baseYaw, 8, dt);
    const scale = 0.88 * (active ? 1.015 : 1);
    terminal.group.scale.setScalar(THREE.MathUtils.damp(terminal.group.scale.x, scale, 8, dt));
  }
}

function alpeccaDashboardStatusColor() {
  if (alpeccaAiStatus === "live") return "#69ffbd";
  if (alpeccaAiStatus === "connecting") return "#f0bd59";
  if (alpeccaAiStatus === "token") return "#ff6e8e";
  return "#607a80";
}

function alpeccaDashboardFeatureValue(featureId: string) {
  const stateValue = (key: string) => {
    const raw = alpeccaAiState[key];
    return Number.isFinite(raw) ? THREE.MathUtils.clamp(raw, 0, 1) : 0;
  };
  if (featureId === "self") return Math.max(stateValue("love"), stateValue("compassion"));
  if (featureId === "memory" || featureId === "journal") return stateValue("compassion");
  if (featureId === "studio" || featureId === "home") return stateValue("energy");
  if (featureId === "soul") return Math.max(0, 1 - stateValue("fear"));
  return 0;
}

function pulseAlpeccaSourceDashboard(featureId = "", seconds = 2.6) {
  if (!alpeccaSourceDashboard) return;
  alpeccaSourceDashboard.pulseTimer = Math.max(alpeccaSourceDashboard.pulseTimer, seconds * 0.72);
  if (featureId) {
    alpeccaSourceDashboard.activeFeatureId = featureId;
    const node = alpeccaSourceDashboard.nodes.find((item) => item.featureId === featureId);
    if (node) node.pulseTimer = Math.max(node.pulseTimer, seconds);
  } else {
    for (const node of alpeccaSourceDashboard.nodes) node.pulseTimer = Math.max(node.pulseTimer, seconds * 0.42);
  }
}

function alpeccaSourceDashboardSummary() {
  const feature = alpeccaSourceFeatures[alpeccaSourceDashboard?.activeFeatureId || "home"] ?? alpeccaSourceFeatures.home;
  const status =
    alpeccaAiStatus === "live"
      ? `Live mood: ${alpeccaAiMood}`
      : alpeccaAiStatus === "connecting"
        ? "Connecting to live source"
        : alpeccaAiStatus === "token"
          ? "Waiting for shared source identity"
          : "Offline fallback active";
  return `Alpecca source dashboard: ${status}. Active node: ${feature.room}. ${activeEnvironmentLabel()} progress ${activatedRooms}/${activeRoomTotal()}.`;
}

function addAlpeccaSourceDashboard(pos: THREE.Vector3Tuple, yaw: number) {
  const group = new THREE.Group();
  group.name = "Alpecca source systems dashboard";
  group.position.set(pos[0], 0, pos[2]);
  group.rotation.y = yaw;
  group.scale.setScalar(0.92);
  scene.add(group);

  groupBox(group, [1.58, 0.14, 0.74], [0, 0.12, 0], materials.metal);
  groupBox(group, [1.32, 0.08, 0.46], [0, 0.23, 0.05], materials.darkWood);
  groupBox(group, [1.48, 0.92, 0.08], [0, 0.75, -0.22], materials.board);
  groupBox(group, [1.6, 0.055, 0.1], [0, 1.24, -0.18], materials.metal);
  groupBox(group, [1.6, 0.055, 0.1], [0, 0.27, -0.18], materials.metal);
  groupBox(group, [0.06, 0.9, 0.1], [-0.78, 0.75, -0.18], materials.metal);
  groupBox(group, [0.06, 0.9, 0.1], [0.78, 0.75, -0.18], materials.metal);
  groupBox(group, [0.1, 0.72, 0.1], [-0.6, 0.45, 0.16], materials.metal);
  groupBox(group, [0.1, 0.72, 0.1], [0.6, 0.45, 0.16], materials.metal);
  addContactOcclusion("Alpecca source dashboard contact ao", [1.82, 0.95], [pos[0], 0.012, pos[2]], 0.17);
  addGroundCable(
    "Alpecca source dashboard trunk cable",
    [pos[0], 0.04, pos[2]],
    [pos[0] - Math.sin(yaw) * 0.72, 0.04, pos[2] - Math.cos(yaw) * 0.72],
    alpeccaSourceFeatures.home.color,
  );

  const statusMaterial = new THREE.MeshBasicMaterial({
    color: alpeccaDashboardStatusColor(),
    transparent: true,
    opacity: 0.28,
    depthWrite: false,
  });
  const statusRail = new THREE.Mesh(new THREE.BoxGeometry(1.08, 0.035, 0.025), statusMaterial);
  statusRail.name = "Alpecca source dashboard status rail";
  statusRail.position.set(0, 1.08, -0.115);
  statusRail.renderOrder = 7;
  group.add(statusRail);

  const coreMaterial = new THREE.MeshBasicMaterial({
    color: alpeccaDashboardStatusColor(),
    transparent: true,
    opacity: 0.58,
    depthWrite: false,
  });
  const core = new THREE.Mesh(new THREE.OctahedronGeometry(0.12, 0), coreMaterial);
  core.name = "Alpecca source dashboard live core";
  core.position.set(0, 0.82, -0.1);
  core.renderOrder = 8;
  group.add(core);

  const statusLight = new THREE.PointLight(alpeccaDashboardStatusColor(), 0.22, 2.8, 2);
  statusLight.position.set(0, 0.95, 0.12);
  group.add(statusLight);

  const featureIds = ["home", "self", "memory", "journal", "studio", "soul"];
  const nodes: AlpeccaSourceDashboardNode[] = [];
  for (const [index, featureId] of featureIds.entries()) {
    const feature = alpeccaSourceFeatures[featureId];
    const col = index % 3;
    const row = Math.floor(index / 3);
    const x = -0.46 + col * 0.46;
    const y = 0.63 - row * 0.28;
    const material = new THREE.MeshBasicMaterial({
      color: feature.color,
      transparent: true,
      opacity: 0.34,
      depthWrite: false,
    });
    const node = new THREE.Mesh(new THREE.SphereGeometry(0.055, 18, 12), material);
    node.name = `${feature.room} source dashboard node`;
    node.position.set(x, y, -0.105);
    node.renderOrder = 9;
    group.add(node);

    const railMaterial = material.clone();
    railMaterial.opacity = 0.18;
    const rail = new THREE.Mesh(new THREE.BoxGeometry(0.28, 0.024, 0.018), railMaterial);
    rail.name = `${feature.room} source dashboard rail`;
    rail.position.set(x, y - 0.105, -0.102);
    rail.renderOrder = 8;
    group.add(rail);

    const light = new THREE.PointLight(feature.color, 0.04, 1.6, 2);
    light.position.set(x, y, 0.08);
    group.add(light);
    nodes.push({ featureId, material, railMaterial, mesh: node, rail, light, pulseTimer: 0 });
  }

  alpeccaSourceDashboard = {
    group,
    nodes,
    core,
    coreMaterial,
    statusMaterial,
    statusLight,
    pulseTimer: 0,
    activeFeatureId: "home",
  };
  window.__HOUSE_DEBUG__!.sourceDashboard = {
    ready: true,
    activeFeatureId: "home",
    nodes: nodes.length,
    status: alpeccaAiStatus,
  };

  register({
    id: "alpecca-source-dashboard",
    label: "Inspect Alpecca source dashboard",
    root: group,
    range: 2.4,
    type: "momentary",
    onUse: () => {
      pulseAlpeccaSourceDashboard("", 2.8);
      focusAlpecca(1.6, "idleDown");
      return alpeccaSourceDashboardSummary();
    },
  });
}

function updateAlpeccaSourceDashboard(dt: number) {
  if (!alpeccaSourceDashboard) return;
  const dashboard = alpeccaSourceDashboard;
  const now = performance.now();
  if (dashboard.pulseTimer > 0) dashboard.pulseTimer -= dt;
  const liveActivity = alpeccaAiStatus === "live" || alpeccaAiAwaitingReply;
  const statusColor = alpeccaDashboardStatusColor();
  dashboard.statusMaterial.color.set(statusColor);
  dashboard.coreMaterial.color.set(statusColor);
  dashboard.statusLight.color.set(statusColor);

  const coreActive = dashboard.pulseTimer > 0 || liveActivity;
  const coreOpacity = coreActive ? 0.44 + Math.sin(now / 190) * 0.08 : 0.2 + Math.sin(now / 1200) * 0.025;
  dashboard.coreMaterial.opacity = THREE.MathUtils.damp(dashboard.coreMaterial.opacity, coreOpacity * calmVisualMultiplier(coreActive), 8, dt);
  dashboard.statusMaterial.opacity = THREE.MathUtils.damp(dashboard.statusMaterial.opacity, (coreActive ? 0.32 : 0.16) * calmVisualMultiplier(coreActive), 8, dt);
  dashboard.statusLight.intensity = THREE.MathUtils.damp(dashboard.statusLight.intensity, (coreActive ? 0.28 : 0.08) * calmLightMultiplier(coreActive), 7, dt);
  dashboard.core.rotation.x += dt * (coreActive ? 0.7 : 0.14);
  dashboard.core.rotation.y += dt * (coreActive ? 1.15 : 0.22);

  for (const node of dashboard.nodes) {
    if (node.pulseTimer > 0) node.pulseTimer -= dt;
    const stateValue = alpeccaDashboardFeatureValue(node.featureId);
    const selected = dashboard.activeFeatureId === node.featureId;
    const active = selected || node.pulseTimer > 0 || (alpeccaAiStatus === "live" && stateValue > 0.58);
    const pulse = active ? 0.36 + Math.sin(now / 160 + node.mesh.position.x * 3) * 0.08 : 0.18;
    const opacity = pulse + stateValue * 0.16;
    node.material.opacity = THREE.MathUtils.damp(node.material.opacity, THREE.MathUtils.clamp(opacity * calmVisualMultiplier(active), 0.08, 0.58), 8, dt);
    node.railMaterial.opacity = THREE.MathUtils.damp(node.railMaterial.opacity, (active ? 0.32 : 0.12 + stateValue * 0.14) * calmVisualMultiplier(active), 8, dt);
    node.light.intensity = THREE.MathUtils.damp(node.light.intensity, (active ? 0.18 + stateValue * 0.12 : 0.03) * calmLightMultiplier(active), 8, dt);
    node.mesh.scale.setScalar(THREE.MathUtils.damp(node.mesh.scale.x, active ? 1.08 : 0.94, 8, dt));
    node.mesh.rotation.y += dt * (active ? 0.9 : 0.18);
  }
  if (window.__HOUSE_DEBUG__?.sourceDashboard) {
    window.__HOUSE_DEBUG__.sourceDashboard.ready = true;
    window.__HOUSE_DEBUG__.sourceDashboard.activeFeatureId = dashboard.activeFeatureId;
    window.__HOUSE_DEBUG__.sourceDashboard.nodes = dashboard.nodes.length;
    window.__HOUSE_DEBUG__.sourceDashboard.status = alpeccaAiStatus;
  }
}

function colorForAlpeccaSourcePlate(plateId: string) {
  if (plateId === "movement") return alpeccaSourceFeatures.studio.color;
  if (plateId === "gestures") return alpeccaSourceFeatures.home.color;
  if (plateId === "expressions") return alpeccaSourceFeatures.memory.color;
  if (plateId === "wardrobe") return alpeccaSourceFeatures.self.color;
  return "#8eeeff";
}

function fitSourceArtPanel(
  art: THREE.Mesh<THREE.PlaneGeometry, THREE.MeshBasicMaterial>,
  texture: THREE.Texture,
  maxWidth: number,
  maxHeight: number,
) {
  const image = texture.image as { width?: number; height?: number };
  const width = Math.max(1, image.width ?? 1);
  const height = Math.max(1, image.height ?? 1);
  const aspect = width / height;
  const boxAspect = maxWidth / maxHeight;
  const panelWidth = aspect > boxAspect ? maxWidth : maxHeight * aspect;
  const panelHeight = aspect > boxAspect ? maxWidth / aspect : maxHeight;
  art.scale.set(panelWidth, panelHeight, 1);
}

function applySourceArtTexture(
  art: THREE.Mesh<THREE.PlaneGeometry, THREE.MeshBasicMaterial>,
  file: string,
  maxWidth: number,
  maxHeight: number,
) {
  loadTexture(`${alpeccaSourceArtRoot}/${file}.webp`)
    .catch(() => loadTexture(`${alpeccaSourceArtRoot}/${file}.png`))
    .then((texture) => {
      texture.colorSpace = THREE.SRGBColorSpace;
      texture.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy());
      texture.minFilter = THREE.LinearMipmapLinearFilter;
      texture.magFilter = THREE.LinearFilter;
      texture.needsUpdate = true;
      art.material.map = texture;
      art.material.color.set("#ffffff");
      art.material.needsUpdate = true;
      fitSourceArtPanel(art, texture, maxWidth, maxHeight);
    })
    .catch(() => {
      art.material.color.set("#293537");
      art.material.needsUpdate = true;
    });
}

function addAlpeccaSourceGalleryPanel(
  plateId: string,
  roomId: string,
  pos: THREE.Vector3Tuple,
  yaw: number,
  maxWidth = 1.48,
  maxHeight = 0.94,
) {
  const plate = alpeccaSourcePlates[plateId] ?? alpeccaSourcePlates.master;
  const color = colorForAlpeccaSourcePlate(plate.id);
  const group = new THREE.Group();
  group.name = `${plate.label} 3D source art panel`;
  group.position.set(...pos);
  group.rotation.y = yaw;
  scene.add(group);

  groupBox(group, [maxWidth + 0.22, maxHeight + 0.22, 0.06], [0, 0, -0.045], materials.board);
  groupBox(group, [maxWidth + 0.06, 0.045, 0.08], [0, maxHeight / 2 + 0.08, 0.01], materials.metal);
  groupBox(group, [maxWidth + 0.06, 0.045, 0.08], [0, -maxHeight / 2 - 0.08, 0.01], materials.metal);
  groupBox(group, [0.06, maxHeight + 0.28, 0.09], [-maxWidth / 2 - 0.08, 0, -0.015], materials.metal);
  groupBox(group, [0.06, maxHeight + 0.28, 0.09], [maxWidth / 2 + 0.08, 0, -0.015], materials.metal);
  addPanelCableDrop(group, maxWidth / 2 - 0.18, -maxHeight / 2 - 0.11, pos[1], 0.04, materials.metal);
  addContactOcclusion(`${plate.label} source art floor cable ao`, [0.62, 0.34], [pos[0], 0.012, pos[2]], 0.08);

  const artMaterial = new THREE.MeshBasicMaterial({
    color: "#293537",
    side: THREE.DoubleSide,
  });
  const art = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), artMaterial);
  art.name = `${plate.label} source art image`;
  art.position.set(0, 0, 0.014);
  art.renderOrder = 6;
  group.add(art);

  const accentMaterial = new THREE.MeshBasicMaterial({
    color,
    transparent: true,
    opacity: 0.28,
    depthWrite: false,
  });
  const core = new THREE.Mesh(new THREE.OctahedronGeometry(0.075, 0), accentMaterial);
  core.name = `${plate.label} source art status core`;
  core.position.set(maxWidth / 2 - 0.12, maxHeight / 2 - 0.12, 0.055);
  core.renderOrder = 7;
  group.add(core);
  const rail = new THREE.Mesh(new THREE.BoxGeometry(maxWidth * 0.42, 0.035, 0.03), accentMaterial);
  rail.name = `${plate.label} source art status rail`;
  rail.position.set(-maxWidth * 0.22, -maxHeight / 2 + 0.1, 0.05);
  rail.renderOrder = 7;
  group.add(rail);

  const light = new THREE.PointLight(color, 0.08, 2.4, 2);
  light.position.set(pos[0], pos[1], pos[2]);
  scene.add(light);

  applySourceArtTexture(art, plate.file, maxWidth, maxHeight);
  alpeccaSourceGalleryPanels.set(plate.id, { plateId: plate.id, roomId, group, art, accentMaterial, core, light, pulseTimer: 0 });

  register({
    id: `source-art-${plate.id}`,
    label: `Study ${plate.label}`,
    root: group,
    range: 2.35,
    type: "momentary",
    onUse: () => {
      setAlpeccaSourcePlate(plate.id);
      pulseAlpeccaSourceGallery(plate.id, 3.2);
      pulseAlpeccaRoomDevice(roomId, 2.2);
      focusAlpecca(1.4, plate.id === "movement" ? "idleSide" : plate.id === "gestures" ? "point" : "idleDown");
      return `${plate.label}: ${plate.hint}.`;
    },
  });
}

function pulseAlpeccaSourceGallery(plateId: string, seconds = 2.4) {
  const panel = alpeccaSourceGalleryPanels.get(plateId);
  if (!panel) return;
  panel.pulseTimer = Math.max(panel.pulseTimer, seconds);
}

function updateAlpeccaSourceGalleryPanels(dt: number) {
  const now = performance.now();
  for (const panel of alpeccaSourceGalleryPanels.values()) {
    if (panel.pulseTimer > 0) panel.pulseTimer -= dt;
    const selected = currentAlpeccaSourcePlate === panel.plateId;
    const active = panel.pulseTimer > 0 || selected;
    const glow = active ? 0.42 + Math.sin(now / 135 + panel.group.position.x) * 0.16 : 0.18;
    panel.accentMaterial.opacity = THREE.MathUtils.damp(panel.accentMaterial.opacity, glow * calmVisualMultiplier(active), 8, dt);
    panel.light.intensity = THREE.MathUtils.damp(panel.light.intensity, (active ? 0.34 : 0.06) * calmLightMultiplier(active), 7, dt);
    panel.core.rotation.y += dt * (active ? 2.4 : 0.42);
    panel.core.rotation.x += dt * (active ? 1.1 : 0.18);
  }
}

function expressionForAlpeccaState() {
  const mood = alpeccaAiMood.toLowerCase();
  const love = Number.isFinite(alpeccaAiState.love) ? alpeccaAiState.love : 0;
  const compassion = Number.isFinite(alpeccaAiState.compassion) ? alpeccaAiState.compassion : 0;
  const fear = Number.isFinite(alpeccaAiState.fear) ? alpeccaAiState.fear : 0;
  const energy = Number.isFinite(alpeccaAiState.energy) ? alpeccaAiState.energy : 0.45;

  if (alpeccaAiAwaitingReply || mood.includes("thinking")) return "thinking";
  if (alpecca.inspectTimer > 0) return "curious";
  if (mood.includes("overload")) return "overload";
  if (fear > 0.72 || ["fearful", "anxious", "worried"].some((word) => mood.includes(word))) return "fear_spike";
  if (mood.includes("protective")) return "protective";
  if (mood.includes("apologetic")) return "apologetic";
  if (mood.includes("concerned") || alpeccaAiStatus === "token") return "concerned";
  if (energy < 0.16 || ["sleepy", "withdrawn", "low"].some((word) => mood.includes(word))) return "low_power";
  if (mood.includes("sad") || mood.includes("lonely")) return "soft_sadness";
  if (mood.includes("playful")) return "playful";
  if (mood.includes("joyful") || mood.includes("happy")) return "happy";
  if (love > 0.72 || mood.includes("affectionate")) return "warm_smile";
  if (compassion > 0.7 || mood.includes("compassion")) return "compassionate";
  if (mood.includes("reassuring")) return "reassuring";
  if (mood.includes("gentle")) return "gentle";
  return alpeccaAiStatus === "live" ? "warm_smile" : "neutral";
}

function loadAlpeccaExpressionTexture(id: string) {
  const cached = alpeccaExpressionTextures.get(id);
  if (cached) return Promise.resolve(cached);
  return loadTexture(`${alpeccaExpressionRoot}/${id}.png`).then((texture) => {
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy());
    texture.minFilter = THREE.LinearMipmapLinearFilter;
    texture.magFilter = THREE.LinearFilter;
    texture.needsUpdate = true;
    alpeccaExpressionTextures.set(id, texture);
    return texture;
  });
}

function setAlpeccaExpressionProjector(id: string, pulse = true) {
  if (!alpeccaExpressionProjector || alpeccaExpressionProjector.current === id) return;
  alpeccaExpressionProjector.current = id;
  if (pulse) alpeccaExpressionProjector.pulseTimer = Math.max(alpeccaExpressionProjector.pulseTimer, 1.8);
  void loadAlpeccaExpressionTexture(id)
    .then((texture) => {
      if (!alpeccaExpressionProjector || alpeccaExpressionProjector.current !== id) return;
      alpeccaExpressionProjector.portrait.material.map = texture;
      alpeccaExpressionProjector.portrait.material.color.set("#ffffff");
      alpeccaExpressionProjector.portrait.material.needsUpdate = true;
    })
    .catch(() => {
      if (!alpeccaExpressionProjector) return;
      alpeccaExpressionProjector.portrait.material.color.set("#2b3638");
      alpeccaExpressionProjector.portrait.material.needsUpdate = true;
    });
}

function syncAlpeccaExpressionProjector() {
  if (alpeccaExpressionManualTimer > 0) return;
  setAlpeccaExpressionProjector(expressionForAlpeccaState(), false);
}

function addAlpeccaExpressionProjector(pos: THREE.Vector3Tuple, yaw: number) {
  const group = new THREE.Group();
  group.name = "Alpecca expression mood projector";
  group.position.set(...pos);
  group.rotation.y = yaw;
  group.scale.setScalar(0.64);
  scene.add(group);

  groupBox(group, [0.95, 1.08, 0.07], [0, 0, -0.04], materials.board);
  groupBox(group, [1.08, 0.05, 0.08], [0, 0.6, 0.01], materials.metal);
  groupBox(group, [1.08, 0.05, 0.08], [0, -0.6, 0.01], materials.metal);
  groupBox(group, [0.04, 1.05, 0.08], [-0.55, 0, 0.01], materials.metal);
  groupBox(group, [0.04, 1.05, 0.08], [0.55, 0, 0.01], materials.metal);
  groupBox(group, [0.18, 0.08, 0.12], [-0.42, -0.68, 0.035], materials.metal);
  groupBox(group, [0.18, 0.08, 0.12], [0.42, -0.68, 0.035], materials.metal);
  addPanelCableDrop(group, 0.47, -0.68, pos[1], 0.06, materials.metal);
  addContactOcclusion("Alpecca expression projector cable ao", [0.58, 0.32], [pos[0], 0.012, pos[2]], 0.1);

  const portraitMaterial = new THREE.MeshBasicMaterial({ color: "#2b3638", side: THREE.DoubleSide });
  const portrait = new THREE.Mesh(new THREE.PlaneGeometry(0.82, 0.92), portraitMaterial);
  portrait.name = "Alpecca expression portrait";
  portrait.position.set(0, 0.02, 0.02);
  portrait.renderOrder = 8;
  group.add(portrait);

  const frameMaterial = new THREE.MeshBasicMaterial({
    color: "#4be4ff",
    transparent: true,
    opacity: 0.22,
    depthWrite: false,
  });
  const core = new THREE.Mesh(new THREE.OctahedronGeometry(0.08, 0), frameMaterial);
  core.name = "Alpecca expression mood core";
  core.position.set(0.45, 0.48, 0.06);
  core.renderOrder = 9;
  group.add(core);

  const light = new THREE.PointLight("#4be4ff", 0.12, 2.5, 2);
  light.position.set(pos[0], pos[1] + 0.15, pos[2]);
  scene.add(light);

  alpeccaExpressionProjector = { group, portrait, frameMaterial, core, light, current: "", pulseTimer: 0 };
  setAlpeccaExpressionProjector("neutral", false);

  register({
    id: "alpecca-expression-projector",
    label: "Cycle Alpecca expression",
    root: group,
    range: 1.65,
    type: "momentary",
    onUse: () => {
      alpeccaExpressionCycleIndex = (alpeccaExpressionCycleIndex + 1) % alpeccaExpressionIds.length;
      const expression = alpeccaExpressionIds[alpeccaExpressionCycleIndex];
      alpeccaExpressionManualTimer = 5.5;
      setAlpeccaExpressionProjector(expression, true);
      pulseAlpeccaRoomDevice("self-design", 2.4);
      focusAlpecca(1.4, expression === "thinking" ? "point" : expression === "low_power" ? "sit" : "idleDown");
      return `Expression projector: ${expression.replace(/_/g, " ")}.`;
    },
  });
}

function updateAlpeccaExpressionProjector(dt: number) {
  if (!alpeccaExpressionProjector) return;
  if (alpeccaExpressionManualTimer > 0) alpeccaExpressionManualTimer -= dt;
  if (alpeccaExpressionProjector.pulseTimer > 0) alpeccaExpressionProjector.pulseTimer -= dt;
  syncAlpeccaExpressionProjector();

  const now = performance.now();
  const active = alpeccaExpressionProjector.pulseTimer > 0 || alpeccaAiAwaitingReply || alpecca.inspectTimer > 0;
  const glow = active ? 0.5 + Math.sin(now / 120) * 0.18 : 0.2 + Math.sin(now / 760) * 0.04;
  alpeccaExpressionProjector.frameMaterial.opacity = THREE.MathUtils.damp(alpeccaExpressionProjector.frameMaterial.opacity, glow * calmVisualMultiplier(active), 8, dt);
  alpeccaExpressionProjector.core.rotation.x += dt * (active ? 1.6 : 0.35);
  alpeccaExpressionProjector.core.rotation.y += dt * (active ? 2.4 : 0.55);
  alpeccaExpressionProjector.light.intensity = THREE.MathUtils.damp(alpeccaExpressionProjector.light.intensity, (active ? 0.48 : 0.1) * calmLightMultiplier(active), 7, dt);
}

function alpeccaAvatarAsset(id: string) {
  return alpeccaAvatarAssets.find((asset) => asset.id === id) ?? alpeccaAvatarAssets[1];
}

function avatarForAlpeccaState() {
  const mood = alpeccaAiMood.toLowerCase();
  const energy = Number.isFinite(alpeccaAiState.energy) ? alpeccaAiState.energy : 0.45;
  const fear = Number.isFinite(alpeccaAiState.fear) ? alpeccaAiState.fear : 0;

  if (alpeccaAiAwaitingReply) return "portrait_thinking";
  if (!alpeccaChat.classList.contains("hidden") || alpeccaLiveAttentionTimer > 0) return "portrait_speaking";
  if (alpecca.moving) return "pose_walk";
  if (alpecca.inspectTimer > 0 && alpecca.state === "point") return "pose_reach";
  if (alpecca.inspectTimer > 0) return "pose_present";
  if (alpecca.state === "wave" || alpecca.state === "victory" || alpecca.state === "dance") return "pose_present";
  if (alpecca.state === "sit" || alpecca.state === "sleep" || energy < 0.16) return "pose_rest";
  if (fear > 0.68 || ["anxious", "worried", "fearful"].some((word) => mood.includes(word))) return "pose_shy";
  if (mood.includes("thinking")) return "portrait_thinking";
  return alpeccaAiStatus === "live" ? "portrait_idle" : "source";
}

function fitAvatarStationImage(texture: THREE.Texture) {
  if (!alpeccaAvatarStation) return;
  const image = texture.image as { width?: number; height?: number };
  const width = Math.max(1, image.width ?? 1);
  const height = Math.max(1, image.height ?? 1);
  const aspect = width / height;
  const maxWidth = 1.06;
  const maxHeight = 1.28;
  const boxAspect = maxWidth / maxHeight;
  const panelWidth = aspect > boxAspect ? maxWidth : maxHeight * aspect;
  const panelHeight = aspect > boxAspect ? maxWidth / aspect : maxHeight;
  alpeccaAvatarStation.image.scale.set(panelWidth, panelHeight, 1);
}

function loadAlpeccaAvatarTexture(asset: AlpeccaAvatarAsset) {
  const cached = alpeccaAvatarTextures.get(asset.id);
  if (cached) return Promise.resolve(cached);
  return loadTexture(`${alpeccaAvatarRoot}/${asset.file}.png`).then((texture) => {
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy());
    texture.minFilter = THREE.LinearMipmapLinearFilter;
    texture.magFilter = THREE.LinearFilter;
    texture.needsUpdate = true;
    alpeccaAvatarTextures.set(asset.id, texture);
    return texture;
  });
}

function setAlpeccaAvatarStation(id: string, pulse = true) {
  if (!alpeccaAvatarStation || alpeccaAvatarStation.current === id) return;
  const asset = alpeccaAvatarAsset(id);
  alpeccaAvatarStation.current = asset.id;
  if (pulse) alpeccaAvatarStation.pulseTimer = Math.max(alpeccaAvatarStation.pulseTimer, 1.8);
  void loadAlpeccaAvatarTexture(asset)
    .then((texture) => {
      if (!alpeccaAvatarStation || alpeccaAvatarStation.current !== asset.id) return;
      alpeccaAvatarStation.image.material.map = texture;
      alpeccaAvatarStation.image.material.color.set("#ffffff");
      alpeccaAvatarStation.image.material.needsUpdate = true;
      fitAvatarStationImage(texture);
    })
    .catch(() => {
      if (!alpeccaAvatarStation) return;
      alpeccaAvatarStation.image.material.color.set("#243235");
      alpeccaAvatarStation.image.material.needsUpdate = true;
    });
}

function syncAlpeccaAvatarStation() {
  if (alpeccaAvatarManualTimer > 0) return;
  setAlpeccaAvatarStation(avatarForAlpeccaState(), false);
}

function addAlpeccaAvatarStation(pos: THREE.Vector3Tuple, yaw: number) {
  const group = new THREE.Group();
  group.name = "Alpecca avatar pose station";
  group.position.set(...pos);
  group.rotation.y = yaw;
  group.scale.setScalar(0.88);
  scene.add(group);

  groupBox(group, [1.34, 1.58, 0.07], [0, 0, -0.045], materials.board);
  groupBox(group, [1.48, 0.06, 0.09], [0, 0.84, 0.01], materials.metal);
  groupBox(group, [1.48, 0.06, 0.09], [0, -0.84, 0.01], materials.metal);
  groupBox(group, [0.06, 1.48, 0.09], [-0.74, 0, 0.01], materials.metal);
  groupBox(group, [0.06, 1.48, 0.09], [0.74, 0, 0.01], materials.metal);
  groupBox(group, [0.2, 0.08, 0.12], [-0.52, -0.92, 0.04], materials.metal);
  groupBox(group, [0.2, 0.08, 0.12], [0.52, -0.92, 0.04], materials.metal);
  addPanelCableDrop(group, -0.58, -0.92, pos[1], 0.06, materials.metal);
  addContactOcclusion("Alpecca avatar station cable ao", [0.62, 0.36], [pos[0], 0.012, pos[2]], 0.1);

  const imageMaterial = new THREE.MeshBasicMaterial({ color: "#243235", side: THREE.DoubleSide });
  const image = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), imageMaterial);
  image.name = "Alpecca avatar pose image";
  image.position.set(0, 0, 0.018);
  image.renderOrder = 8;
  group.add(image);

  const frameMaterial = new THREE.MeshBasicMaterial({
    color: alpeccaSourceFeatures.self.color,
    transparent: true,
    opacity: 0.22,
    depthWrite: false,
  });
  const core = new THREE.Mesh(new THREE.OctahedronGeometry(0.085, 0), frameMaterial);
  core.name = "Alpecca avatar pose core";
  core.position.set(0.61, 0.66, 0.06);
  core.renderOrder = 9;
  group.add(core);

  const light = new THREE.PointLight(alpeccaSourceFeatures.self.color, 0.12, 2.6, 2);
  light.position.set(pos[0], pos[1] + 0.12, pos[2]);
  scene.add(light);

  alpeccaAvatarStation = { group, image, frameMaterial, core, light, current: "", pulseTimer: 0 };
  setAlpeccaAvatarStation("source", false);

  register({
    id: "alpecca-avatar-pose-station",
    label: "Cycle Alpecca avatar pose",
    root: group,
    range: 2.35,
    type: "momentary",
    onUse: () => {
      alpeccaAvatarCycleIndex = (alpeccaAvatarCycleIndex + 1) % alpeccaAvatarAssets.length;
      const asset = alpeccaAvatarAssets[alpeccaAvatarCycleIndex];
      alpeccaAvatarManualTimer = 6;
      setAlpeccaAvatarStation(asset.id, true);
      pulseAlpeccaRoomDevice("self-design", 2.2);
      pulseAlpeccaRoomDetails("self-design", 1.8);
      focusAlpecca(1.35, asset.id === "pose_walk" ? "idleSide" : asset.id === "pose_reach" ? "point" : "idleDown");
      return `Avatar pose station: ${asset.label}.`;
    },
  });
}

function updateAlpeccaAvatarStation(dt: number) {
  if (!alpeccaAvatarStation) return;
  if (alpeccaAvatarManualTimer > 0) alpeccaAvatarManualTimer -= dt;
  if (alpeccaAvatarStation.pulseTimer > 0) alpeccaAvatarStation.pulseTimer -= dt;
  syncAlpeccaAvatarStation();

  const now = performance.now();
  const active = alpeccaAvatarStation.pulseTimer > 0 || alpecca.moving || alpeccaAiAwaitingReply || !alpeccaChat.classList.contains("hidden");
  const glow = active ? 0.5 + Math.sin(now / 115) * 0.18 : 0.18 + Math.sin(now / 820) * 0.04;
  alpeccaAvatarStation.frameMaterial.opacity = THREE.MathUtils.damp(alpeccaAvatarStation.frameMaterial.opacity, glow * calmVisualMultiplier(active), 8, dt);
  alpeccaAvatarStation.core.rotation.x += dt * (active ? 1.3 : 0.25);
  alpeccaAvatarStation.core.rotation.y += dt * (active ? 2.2 : 0.45);
  alpeccaAvatarStation.light.intensity = THREE.MathUtils.damp(alpeccaAvatarStation.light.intensity, (active ? 0.45 : 0.1) * calmLightMultiplier(active), 7, dt);
}

function addAlpeccaRoomDevice(roomId: string, label: string, pos: THREE.Vector3Tuple, color = "#8eeeff") {
  const group = new THREE.Group();
  group.name = `${label} Alpecca room device`;
  group.position.set(pos[0], 0.034, pos[2]);
  scene.add(group);

  const material = new THREE.MeshBasicMaterial({
    color,
    transparent: true,
    opacity: 0.16,
    depthWrite: false,
  });
  const ring = new THREE.Mesh(new THREE.RingGeometry(0.22, 0.3, 36), material);
  ring.name = `${label} scan ring`;
  ring.rotation.x = -Math.PI / 2;
  ring.renderOrder = 5;
  group.add(ring);

  const beam = new THREE.Mesh(new THREE.CylinderGeometry(0.018, 0.07, 0.95, 16, 1, true), material);
  beam.name = `${label} scan beam`;
  beam.position.set(0, 0.48, 0);
  beam.renderOrder = 5;
  group.add(beam);

  const core = new THREE.Mesh(new THREE.OctahedronGeometry(0.11, 0), material);
  core.name = `${label} scan core`;
  core.position.set(0, Math.max(0.62, pos[1] * 0.72), 0);
  core.renderOrder = 6;
  group.add(core);

  const light = new THREE.PointLight(color, 0.08, 2.1, 2);
  light.position.set(pos[0], Math.max(0.85, pos[1]), pos[2]);
  scene.add(light);

  alpeccaRoomDevices.set(roomId, { roomId, label, group, material, light, pulseTimer: 0 });
}

function pulseAlpeccaRoomDevice(roomId: string, seconds = 3.4) {
  const device = alpeccaRoomDevices.get(roomId);
  if (!device) return;
  device.pulseTimer = Math.max(device.pulseTimer, seconds);
}

function updateAlpeccaRoomDevices(dt: number) {
  const now = performance.now();
  for (const device of alpeccaRoomDevices.values()) {
    if (device.pulseTimer > 0) device.pulseTimer -= dt;
    const active = device.pulseTimer > 0;
    const pulse = active ? 0.55 + Math.sin(now / 110) * 0.22 : 0.13 + Math.sin(now / 950 + device.group.position.x) * 0.035;
    device.material.opacity = THREE.MathUtils.damp(device.material.opacity, (active ? pulse : 0.13) * calmVisualMultiplier(active), 9, dt);
    device.group.rotation.y += dt * (active ? 1.45 : 0.18);
    const scale = active ? 1.04 + Math.sin(now / 180) * 0.1 : 0.88;
    device.group.scale.setScalar(THREE.MathUtils.damp(device.group.scale.x, scale, 8, dt));
    device.light.intensity = THREE.MathUtils.damp(device.light.intensity, (active ? 0.78 : 0.08) * calmLightMultiplier(active), 7, dt);
  }
}

function updateAlpeccaDoorAwareness(dt: number) {
  if (!alpecca.ready) return;
  const now = performance.now();
  const routeDoor = alpecca.route[THREE.MathUtils.clamp(alpecca.routeStep, 0, Math.max(0, alpecca.route.length - 1))];

  for (const door of alpeccaAwareDoors) {
    if (door.autoTimer > 0) door.autoTimer -= dt;
    const distanceToAlpecca = Math.hypot(door.root.position.x - alpecca.group.position.x, door.root.position.z - alpecca.group.position.z);
    const routeWillUseDoor =
      !!routeDoor && Math.hypot(door.root.position.x - routeDoor.x, door.root.position.z - routeDoor.z) < 0.75 && distanceToAlpecca < 2.2;
    const nearAlpecca = distanceToAlpecca < 1.35 || routeWillUseDoor;

    if (nearAlpecca) {
      door.autoTimer = Math.max(door.autoTimer, 1.8);
      if (!door.item.active) {
        door.item.active = true;
        door.openedByAlpecca = true;
        pulseAlpeccaRoomDevice(door.roomId, 1.2);
      }
    }

    if (door.openedByAlpecca && door.autoTimer <= 0 && distanceToAlpecca > 1.7) {
      door.item.active = false;
      door.openedByAlpecca = false;
    }

    const active = door.autoTimer > 0 || (door.openedByAlpecca && door.item.active);
    const pulse = active ? 0.42 + Math.sin(now / 130 + door.root.position.x) * 0.15 : 0;
    door.signalMaterial.opacity = THREE.MathUtils.damp(door.signalMaterial.opacity, pulse * calmVisualMultiplier(active), 9, dt);
    door.signalLight.intensity = THREE.MathUtils.damp(door.signalLight.intensity, (active ? 0.28 : 0) * calmLightMultiplier(active), 8, dt);
  }
}

function addAlpeccaActivityMarkers() {
  for (const point of alpeccaExplorePoints) {
    const group = new THREE.Group();
    group.name = `${point.roomName} Alpecca activity marker`;
    group.position.set(point.position.x, 0.025, point.position.z);
    scene.add(group);

    const color = point.featureId ? alpeccaSourceFeatures[point.featureId]?.color ?? "#8eeeff" : "#8eeeff";
    const material = new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity: 0.16,
      depthWrite: false,
    });
    const ring = new THREE.Mesh(new THREE.RingGeometry(0.28, 0.36, 36), material);
    ring.name = `${point.roomName} activity ring`;
    ring.rotation.x = -Math.PI / 2;
    ring.renderOrder = 4;
    group.add(ring);

    const dot = new THREE.Mesh(new THREE.SphereGeometry(0.055, 14, 10), material);
    dot.name = `${point.roomName} activity core`;
    dot.position.set(0, 0.06, 0);
    group.add(dot);

    const beam = new THREE.Mesh(new THREE.CylinderGeometry(0.045, 0.08, 0.72, 18, 1, true), material);
    beam.name = `${point.roomName} activity beam`;
    beam.position.set(0, 0.38, 0);
    beam.renderOrder = 4;
    group.add(beam);

    const glyph = new THREE.Mesh(new THREE.OctahedronGeometry(0.13, 0), material);
    glyph.name = `${point.roomName} activity glyph`;
    glyph.position.set(0, 0.82, 0);
    glyph.renderOrder = 5;
    group.add(glyph);

    const light = new THREE.PointLight(color, 0.08, 1.8, 2);
    light.position.set(point.position.x, 0.42, point.position.z);
    scene.add(light);

    point.marker = group;
    point.markerMaterial = material;
    point.markerLight = light;
    point.markerBeam = beam;
    point.markerGlyph = glyph;
  }
}

function updateAlpeccaActivityMarkers(dt: number) {
  const activePoint = currentAlpeccaExplorePoint();
  const now = performance.now();
  for (const point of alpeccaExplorePoints) {
    if (!point.marker || !point.markerMaterial || !point.markerLight) continue;
    const active = point === activePoint && alpecca.inspectTimer > 0;
    const pulse = active ? 0.75 + Math.sin(now / 145) * 0.22 : 0.18 + Math.sin(now / 900 + point.position.x) * 0.04;
    point.markerMaterial.opacity = THREE.MathUtils.damp(point.markerMaterial.opacity, active ? pulse : 0.22, 9, dt);
    const scale = active ? 1.0 + Math.sin(now / 180) * 0.12 : 0.86;
    point.marker.scale.setScalar(THREE.MathUtils.damp(point.marker.scale.x, scale, 8, dt));
    point.markerLight.intensity = THREE.MathUtils.damp(point.markerLight.intensity, active ? 0.55 : 0.08, 8, dt);
    if (point.markerGlyph) {
      point.markerGlyph.rotation.y += dt * (active ? 2.2 : 0.45);
      point.markerGlyph.position.y = 0.82 + Math.sin(now / 360 + point.position.z) * (active ? 0.05 : 0.025);
    }
  }
}

function addStageQaRect(parent: THREE.Group, rect: RoomStageRect, opacity: number, yOffset = 0) {
  const material = new THREE.MeshBasicMaterial({
    color: rect.color,
    transparent: true,
    opacity,
    depthWrite: false,
    side: THREE.DoubleSide,
  });
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(rect.size.x, rect.size.y), material);
  mesh.name = `QA ${rect.label}`;
  mesh.rotation.x = -Math.PI / 2;
  mesh.position.set(rect.center.x, rect.center.y + yOffset, rect.center.z);
  mesh.renderOrder = 1;
  parent.add(mesh);
  return mesh;
}

function createAlpeccaStageQaGroup() {
  if (alpeccaStageQaGroup) return alpeccaStageQaGroup;
  alpeccaStageQaGroup = new THREE.Group();
  alpeccaStageQaGroup.name = "Alpecca accommodation QA zones";
  scene.add(alpeccaStageQaGroup);
  for (const spec of alpeccaStageSpecs) {
    addStageQaRect(alpeccaStageQaGroup, spec.walkable, 0.045, 0);
    addStageQaRect(alpeccaStageQaGroup, spec.safeLane, 0.07, 0.003);
    addStageQaRect(alpeccaStageQaGroup, spec.stagePad, 0.16, 0.006);
    addStageQaRect(alpeccaStageQaGroup, spec.inspectPad, 0.12, 0.009);
    addStageQaRect(alpeccaStageQaGroup, spec.chatPad, 0.1, 0.012);
    if (spec.restPad) addStageQaRect(alpeccaStageQaGroup, spec.restPad, 0.16, 0.015);
    for (const plane of spec.occlusionPlanes) addStageQaRect(alpeccaStageQaGroup, plane, 0.09, 0.018);
    for (const portal of spec.portals) {
      const portalRect = stageRect(`${portal.id} ${portal.width.toFixed(1)}m`, [portal.center.x, 0.09, portal.center.z], [portal.width, 0.16], "#ffffff");
      addStageQaRect(alpeccaStageQaGroup, portalRect, 0.18, 0.02);
    }
  }
  return alpeccaStageQaGroup;
}

function isAlpeccaCylinderQaMode() {
  if (alpeccaCylinderQaManualVisible !== null) return alpeccaCylinderQaManualVisible;
  const params = new URLSearchParams(window.location.search);
  return params.has("alpecca-cylinder-qa") || params.has("cylinderQa") || params.get("qa") === "cylinder";
}

function addAlpeccaCylinderRing(group: THREE.Group, radius: number, color: string, name: string) {
  const material = new THREE.MeshBasicMaterial({
    color,
    transparent: true,
    opacity: 0.42,
    depthWrite: false,
    side: THREE.DoubleSide,
  });
  const ring = new THREE.Mesh(new THREE.RingGeometry(radius - 0.012, radius + 0.012, 96), material);
  ring.name = name;
  ring.rotation.x = -Math.PI / 2;
  ring.renderOrder = 32;
  group.add(ring);
  return ring;
}

function createAlpeccaCylinderQaGroup() {
  if (alpeccaCylinderQaGroup) return alpeccaCylinderQaGroup;
  alpeccaCylinderQaGroup = new THREE.Group();
  alpeccaCylinderQaGroup.name = "Alpecca 16-sector cylinder QA";
  alpeccaCylinderQaGroup.visible = isAlpeccaCylinderQaMode();
  addAlpeccaCylinderRing(alpeccaCylinderQaGroup, alpeccaCylinderBodyRadius, "#ffffff", "body cylinder ring");
  addAlpeccaCylinderRing(alpeccaCylinderQaGroup, alpeccaCylinderInteractionRadius, "#8eeeff", "interaction cylinder ring");
  addAlpeccaCylinderRing(alpeccaCylinderQaGroup, alpeccaCylinderFarRadius, "#9f8cff", "far cylinder ring");
  addAlpeccaCylinderRing(alpeccaCylinderQaGroup, alpeccaCylinderStageRadius, "#f0bd59", "QA movement cage ring");
  const forward = new THREE.ArrowHelper(new THREE.Vector3(0, 0, 1), new THREE.Vector3(), 1.05, "#8eeeff", 0.18, 0.09);
  forward.name = "Alpecca forward arrow";
  const cameraArrow = new THREE.ArrowHelper(new THREE.Vector3(0, 0, 1), new THREE.Vector3(), 1.35, "#f0bd59", 0.2, 0.1);
  cameraArrow.name = "Camera relative arrow";
  const sectorArrow = new THREE.ArrowHelper(new THREE.Vector3(0, 0, 1), new THREE.Vector3(), 1.62, "#d86a8d", 0.22, 0.11);
  sectorArrow.name = "16-sector selected arrow";
  const moveArrow = new THREE.ArrowHelper(new THREE.Vector3(0, 0, 1), new THREE.Vector3(), 0.92, "#48e08a", 0.16, 0.08);
  moveArrow.name = "Movement direction arrow";
  alpeccaCylinderQaGroup.add(forward, cameraArrow, sectorArrow, moveArrow);
  scene.add(alpeccaCylinderQaGroup);
  return alpeccaCylinderQaGroup;
}

function updateAlpeccaCylinderQaDebug() {
  const group = createAlpeccaCylinderQaGroup();
  const visible = isAlpeccaCylinderQaMode();
  group.visible = visible;
  if (!visible) return;
  group.position.set(alpecca.group.position.x, 0.035, alpecca.group.position.z);
  const bodyYaw = alpecca.groundYaw || alpecca.group.rotation.y;
  const forwardDir = new THREE.Vector3(Math.sin(bodyYaw), 0, Math.cos(bodyYaw)).normalize();
  const toCamera = new THREE.Vector3(camera.position.x - alpecca.group.position.x, 0, camera.position.z - alpecca.group.position.z);
  const cameraDir = toCamera.lengthSq() > 0.0001 ? toCamera.normalize() : forwardDir.clone();
  const sectorYaw = bodyYaw + THREE.MathUtils.degToRad(alpeccaLastViewMatrix.sector16 * 22.5);
  const sectorDir = new THREE.Vector3(Math.sin(sectorYaw), 0, Math.cos(sectorYaw)).normalize();
  const moveDir = alpeccaLastWorldMove.lengthSq() > 0.0001 ? alpeccaLastWorldMove.clone().setY(0).normalize() : forwardDir.clone();
  const arrows = group.children.filter((child): child is THREE.ArrowHelper => child.type === "ArrowHelper");
  const origin = new THREE.Vector3(0, 0.08, 0);
  const configs: Array<[THREE.Vector3, number]> = [
    [forwardDir, 1.05],
    [cameraDir, Math.min(alpeccaCylinderFarRadius, Math.max(0.65, alpeccaLastViewMatrix.cylinderPlayerDistance))],
    [sectorDir, 1.62],
    [moveDir, alpecca.moving ? 0.92 : 0.48],
  ];
  arrows.forEach((arrow, index) => {
    const [dir, length] = configs[index] ?? configs[0];
    arrow.position.copy(origin);
    arrow.setDirection(dir);
    arrow.setLength(length, 0.18, 0.09);
  });
}

function initializeAlpeccaAccommodationQa() {
  alpeccaStageQaIssues = validateAlpeccaAccommodation();
  window.__HOUSE_DEBUG__!.stage = {
    rooms: alpeccaStageSpecs.length,
    issues: alpeccaStageQaIssues,
  };
  if (!isAlpeccaAccommodationQaMode() && !isAlpeccaCylinderQaMode()) return;
  if (isAlpeccaAccommodationQaMode()) createAlpeccaStageQaGroup();
  if (isAlpeccaCylinderQaMode()) createAlpeccaCylinderQaGroup();
  showPerf = true;
  perfEl.classList.remove("hidden");
  showMessage(
    isAlpeccaCylinderQaMode()
      ? "Cylinder QA: 16-sector view rings, arrows, and stage movement cage enabled."
      : alpeccaStageQaIssues.length
        ? `Stage QA found ${alpeccaStageQaIssues.length} accommodation notes.`
        : "Stage QA: all mapped room pads are valid.",
    5,
  );
}

function setAlpeccaStageQaVisible(visible: boolean) {
  const group = createAlpeccaStageQaGroup();
  group.visible = visible;
  showPerf = visible || isAlpeccaCylinderQaMode() || isAlpeccaWalkQaMode();
  perfEl.classList.toggle("hidden", !showPerf);
  if (visible) {
    alpeccaStageQaIssues = validateAlpeccaAccommodation();
    showMessage(alpeccaStageQaIssues.length ? `Stage QA visible: ${alpeccaStageQaIssues.length} notes.` : "Stage QA visible: all mapped pads pass.", 4.5);
  }
}

function setAlpeccaCylinderQaVisible(visible: boolean) {
  alpeccaCylinderQaManualVisible = visible;
  const group = createAlpeccaCylinderQaGroup();
  group.visible = visible;
  showPerf = visible || (alpeccaStageQaGroup?.visible ?? false) || isAlpeccaWalkQaMode();
  perfEl.classList.toggle("hidden", !showPerf);
  showMessage(visible ? "Cylinder QA visible: 16-sector arrows and movement cage active." : "Cylinder QA hidden.", 4.5);
}

function createHouse() {
  box("main floor", [15.5, 0.18, 11.5], [0, -0.09, 0], materials.floor, false);
  box("hq control floor inset", [4.55, 0.028, 3.15], [-4.65, 0.025, 3.05], materials.zone, false);
  box("library floor inset", [4.25, 0.028, 3.05], [-4.82, 0.026, -3.55], materials.zone, false);
  box("self design floor inset", [3.65, 0.026, 1.85], [-5.35, 0.027, 0.45], materials.zoneAlt, false);
  box("observatory floor inset", [4.85, 0.028, 3.3], [5.02, 0.025, 3.35], materials.tile, false);
  box("workshop floor inset", [3.85, 0.028, 3.3], [5.74, 0.026, -3.55], materials.zoneAlt, false);
  box("central hall runner", [1.86, 0.03, 8.8], [0.2, 0.032, -0.25], materials.rug, false);
  addFloorRevealLines();

  addWall("north outer wall left", -4.6, -5.85, 6.6, 0.28);
  addWall("north outer wall right", 4.1, -5.85, 7.2, 0.28);
  addWall("south outer wall left", -4.7, 5.85, 6.8, 0.28);
  addWall("south outer wall right", 4.8, 5.85, 5.5, 0.28);
  addWall("south outer wall sealed center", 0.35, 5.85, 3.0, 0.28);
  addWall("west outer wall", -7.85, 0, 0.28, 11.7);
  addWall("east outer wall", 7.85, 0, 0.28, 11.7);
  addWall("bedroom divider", -1.55, -3.65, 0.25, 4.15);
  addWall("living divider", -1.55, 2.5, 0.25, 2.7);
  addWall("kitchen divider", 2.05, 1.55, 0.25, 4.25);
  addWall("bath divider", 2.05, -4.1, 0.25, 3.5);
  addWall("hall cross wall left", -5.7, -1.25, 4.3, 0.25);
  addWall("hall cross wall right", 5.45, -1.25, 4.8, 0.25);
  addExteriorBoundaryColliders();
  addExteriorWallSealPanels();
  addInteriorWallSkins();
  addInteriorDividerTrim();
  addWallGapSeals();
  addModernWallPanels();

  for (const x of [-6.4, -2.8, 3.3, 6.1]) {
    const windowFrame = box("window frame", [1.05, 0.06, 0.08], [x, 1.75, -5.69], materials.trim, false);
    windowFrame.add(new THREE.Mesh(new THREE.PlaneGeometry(0.86, 0.72), materials.glass));
  }

  addDoor("front door", [0.35, 1.15, 5.48], 0, "Inspect front door", 0, "entry");
  addDoor("bedroom door", [-1.55, 1.15, -1.86], Math.PI / 2, "Open bedroom door", 1, "library");
  addDoor("bathroom door", [2.05, 1.15, -2.12], -Math.PI / 2, "Open bathroom door", -1, "workshop");
  addRoof();
  addCeilingLightPanels();
  addModernDepthLighting();
  addRoomCornerOcclusion();
}

function createPrototypeVoid() {
  scene.background = new THREE.Color("#020506");
  scene.fog = new THREE.Fog("#020506", 10, 24);
  // Spawn on open floor facing the core monitor, clear of the creator console
  // (z=3.25) and chair (z=4.08) so the camera never starts inside them.
  camera.position.set(0.12, 1.55, 2.4);
  // Three.js cameras look down -Z at yaw 0. The avatar/core are north of this
  // spawn, so PI pointed the first-person camera back toward the creator desk.
  player.yaw = 0;
  player.pitch = -0.04;

  const voidFloorMaterial = new THREE.MeshStandardMaterial({
    color: "#070b0c",
    roughness: 0.92,
    metalness: 0.02,
    emissive: "#020708",
    emissiveIntensity: 0.2,
  });
  box("prototype void floor", [11.8, 0.12, 11.8], [0, -0.08, 0], voidFloorMaterial, false, true);
  addCollider(0, -5.98, 12.4, 0.24);
  addCollider(0, 5.98, 12.4, 0.24);
  addCollider(-5.98, 0, 0.24, 12.4);
  addCollider(5.98, 0, 0.24, 12.4);

  const laneMaterial = new THREE.MeshBasicMaterial({ color: "#7de7ff", transparent: true, opacity: 0.1, depthWrite: false });
  const lane = new THREE.Mesh(new THREE.RingGeometry(1.35, 1.39, 96), laneMaterial);
  lane.name = "prototype safe walking lane";
  lane.rotation.x = -Math.PI / 2;
  lane.position.y = 0.012;
  scene.add(lane);

  const focusMaterial = new THREE.MeshBasicMaterial({ color: "#fff0c2", transparent: true, opacity: 0.18, depthWrite: false });
  const focus = new THREE.Mesh(new THREE.CircleGeometry(0.62, 48), focusMaterial);
  focus.name = "creator projector focus";
  focus.rotation.x = -Math.PI / 2;
  focus.position.set(0, 0.014, 3.45);
  scene.add(focus);

  const chair = new THREE.Group();
  chair.name = "creator chair";
  chair.position.set(0, 0, 4.08);
  scene.add(chair);
  groupBox(chair, [0.8, 0.12, 0.72], [0, 0.46, 0], materials.fabric);
  groupBox(chair, [0.88, 0.92, 0.14], [0, 0.9, 0.34], materials.fabric);
  groupBox(chair, [0.11, 0.52, 0.11], [-0.31, 0.24, -0.24], materials.metal);
  groupBox(chair, [0.11, 0.52, 0.11], [0.31, 0.24, -0.24], materials.metal);
  addFurnitureCollider(0, 4.08, 1.05, 0.95);

  const monitorGroup = new THREE.Group();
  monitorGroup.name = "floating core monitor";
  monitorGroup.position.set(0, 1.35, -2.55);
  scene.add(monitorGroup);
  const monitorShell = new THREE.MeshStandardMaterial({ color: "#141b1d", roughness: 0.55, metalness: 0.22 });
  const monitorScreen = new THREE.MeshBasicMaterial({ color: "#4be4ff", transparent: true, opacity: 0.68 });
  groupBox(monitorGroup, [2.7, 1.28, 0.08], [0, 0, 0], monitorShell);
  groupBox(monitorGroup, [2.34, 0.96, 0.055], [0, 0.02, 0.055], monitorScreen);
  const monitorLight = new THREE.PointLight("#4be4ff", 0.8, 5.5, 2);
  monitorLight.position.set(0, 1.35, -2.18);
  scene.add(monitorLight);
  register({
    id: "prototype-core-monitor",
    label: "Open Alpecca core monitor",
    root: monitorGroup,
    range: 2.6,
    type: "momentary",
    onUse: () => {
      runAlpeccaFeature("home");
      return "The floating monitor routes into Alpecca's shared core app.";
    },
  });

  addPrototypeTerminal("memory", [-3.25, 0.85, -0.9], Math.PI / 2, "Memory terminal");
  addPrototypeTerminal("studio", [3.25, 0.85, -0.9], -Math.PI / 2, "Studio terminal");
  addPrototypeTerminal("self", [-2.75, 0.85, 1.62], Math.PI / 2.35, "Self-review terminal");
  addPrototypeTerminal("journal", [2.75, 0.85, 1.62], -Math.PI / 2.35, "Journal terminal");

  addActivationStation("void-core", "Activate prototype core monitor", [0, 1.02, -2.2], "Prototype core is online. Alpecca can test movement, voice, perception, and responses here.");
  addActivationStation("terminal-ring", "Activate terminal ring", [2.72, 1.02, -0.72], "Terminal ring is online. Source tests are available without the full HQ clutter.");
  addActivationStation("creator-light", "Activate creator projector", [0, 1.02, 3.25], "Creator projector is online. Alpecca can use this as a clean focus point.");

  prototypePlayerSpotlight = new THREE.SpotLight("#fff3c4", 1.15, 7.5, Math.PI / 7, 0.48, 1.8);
  prototypePlayerSpotlight.name = "creator hovering projector";
  prototypePlayerSpotlight.position.set(camera.position.x, 4.8, camera.position.z);
  prototypePlayerSpotlight.target.position.set(camera.position.x, 0.02, camera.position.z);
  scene.add(prototypePlayerSpotlight);
  scene.add(prototypePlayerSpotlight.target);
}

function addPrototypeTerminal(featureId: string, pos: THREE.Vector3Tuple, yaw: number, label: string) {
  const feature = alpeccaSourceFeatures[featureId];
  if (!feature) return;
  const group = new THREE.Group();
  group.name = `prototype ${featureId} terminal`;
  group.position.set(...pos);
  group.rotation.y = yaw;
  scene.add(group);

  const accent = new THREE.MeshBasicMaterial({ color: feature.color, transparent: true, opacity: 0.58 });
  groupBox(group, [0.84, 0.08, 0.54], [0, 0.02, 0], materials.metal);
  groupBox(group, [0.72, 0.72, 0.06], [0, 0.48, -0.2], materials.board);
  groupBox(group, [0.56, 0.42, 0.035], [0, 0.52, -0.16], accent);
  groupBox(group, [0.44, 0.035, 0.04], [0, 0.22, -0.13], accent);

  const light = new THREE.PointLight(feature.color, 0.28, 2.6, 2);
  light.position.set(pos[0], pos[1] + 0.25, pos[2]);
  scene.add(light);
  registerAlpeccaTerminalTarget(
    `prototype-${feature.id}`,
    feature.id,
    "terminal-ring",
    label,
    group,
    new THREE.Vector3(0.16, 0.52, -0.13),
    new THREE.Vector3(0, 0.52, -0.16),
  );
  register({
    id: `prototype-${featureId}-terminal`,
    label,
    root: group,
    range: 2.2,
    type: "momentary",
    onUse: () => {
      runAlpeccaFeature(featureId);
      return `${feature.room} linked through the prototype terminal.`;
    },
  });
}

function addFloorRevealFrame(name: string, centerX: number, centerZ: number, sizeX: number, sizeZ: number) {
  const y = 0.052;
  const thickness = 0.035;
  box(`${name} north reveal`, [sizeX, 0.012, thickness], [centerX, y, centerZ - sizeZ / 2], materials.floorLine, false, false);
  box(`${name} south reveal`, [sizeX, 0.012, thickness], [centerX, y, centerZ + sizeZ / 2], materials.floorLine, false, false);
  box(`${name} west reveal`, [thickness, 0.012, sizeZ], [centerX - sizeX / 2, y, centerZ], materials.floorLine, false, false);
  box(`${name} east reveal`, [thickness, 0.012, sizeZ], [centerX + sizeX / 2, y, centerZ], materials.floorLine, false, false);
}

function addFloorRevealLines() {
  addFloorRevealFrame("hq control floor", -4.65, 3.05, 4.62, 3.22);
  addFloorRevealFrame("library floor", -4.82, -3.55, 4.32, 3.12);
  addFloorRevealFrame("self design floor", -5.35, 0.45, 3.72, 1.92);
  addFloorRevealFrame("observatory floor", 5.02, 3.35, 4.92, 3.37);
  addFloorRevealFrame("workshop floor", 5.74, -3.55, 3.92, 3.37);
  box("north hall threshold reveal", [1.82, 0.012, 0.035], [0.2, 0.053, -4.78], materials.floorLine, false, false);
  box("south hall threshold reveal", [1.82, 0.012, 0.035], [0.2, 0.053, 4.28], materials.floorLine, false, false);
  box("center hall reveal left", [0.035, 0.012, 8.68], [-0.72, 0.053, -0.25], materials.floorLine, false, false);
  box("center hall reveal right", [0.035, 0.012, 8.68], [1.12, 0.053, -0.25], materials.floorLine, false, false);
}

function addCeilingLightPanels() {
  const panels: Array<[string, THREE.Vector3Tuple, THREE.Vector3Tuple]> = [
    ["hq control ceiling light panel", [2.4, 0.024, 0.42], [-4.55, 2.765, 3.48]],
    ["library ceiling light panel", [2.2, 0.024, 0.4], [-4.95, 2.765, -3.65]],
    ["observatory ceiling light panel", [2.55, 0.024, 0.42], [5.1, 2.765, 3.42]],
    ["workshop ceiling light panel", [2.2, 0.024, 0.4], [5.62, 2.765, -3.78]],
    ["central hall ceiling light panel", [0.58, 0.024, 4.6], [0.22, 2.766, -0.45]],
  ];
  for (const [name, size, pos] of panels) box(name, size, pos, materials.lightPanel, false, false);
}

function makeDepthWashMaterial(color: string, opacity: number) {
  return new THREE.MeshBasicMaterial({
    color,
    transparent: true,
    opacity,
    depthWrite: false,
    side: THREE.DoubleSide,
  });
}

function addFloorDepthWash(name: string, size: THREE.Vector2Tuple, pos: THREE.Vector3Tuple, color: string, opacity: number) {
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(size[0], size[1]), makeDepthWashMaterial(color, opacity));
  mesh.name = name;
  mesh.rotation.x = -Math.PI / 2;
  mesh.position.set(pos[0], pos[1], pos[2]);
  mesh.renderOrder = 0;
  scene.add(mesh);
}

function addWallDepthWash(name: string, size: THREE.Vector2Tuple, pos: THREE.Vector3Tuple, yaw: number, color: string, opacity: number) {
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(size[0], size[1]), makeDepthWashMaterial(color, opacity));
  mesh.name = name;
  mesh.rotation.y = yaw;
  mesh.position.set(pos[0], pos[1], pos[2]);
  mesh.renderOrder = 0;
  scene.add(mesh);
}

function addModernDepthLighting() {
  addFloorDepthWash("hq control soft floor depth", [3.6, 2.35], [-4.7, 0.057, 3.2], "#f8fff7", 0.11);
  addFloorDepthWash("library soft floor depth", [3.25, 2.35], [-5.15, 0.057, -3.45], "#fff8e6", 0.1);
  addFloorDepthWash("self design soft floor depth", [2.95, 1.32], [-5.55, 0.057, 0.46], "#fff0f6", 0.1);
  addFloorDepthWash("observatory soft floor depth", [3.65, 2.45], [5.05, 0.057, 3.28], "#e8f8ff", 0.105);
  addFloorDepthWash("workshop soft floor depth", [3.15, 2.45], [5.75, 0.057, -3.55], "#f4f2ff", 0.09);
  addWallDepthWash("entry wall depth wash north", [1.18, 1.65], [0.25, 1.48, -5.325], 0, "#eef8f4", 0.12);
  addWallDepthWash("entry wall depth wash south", [1.18, 1.65], [0.25, 1.48, 5.325], Math.PI, "#eef8f4", 0.12);
}

function addRoofPart(group: THREE.Group, name: string, size: THREE.Vector3Tuple, pos: THREE.Vector3Tuple, mat: THREE.Material) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), mat);
  mesh.name = name;
  mesh.position.set(...pos);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  group.add(mesh);
  return mesh;
}

function addRoof() {
  box("interior ceiling", [15.9, 0.12, 11.95], [0, 2.84, 0], materials.ceiling, false, true);

  const halfWidth = 8.35;
  const roofRise = 1.25;
  const roofLength = 12.95;
  const slopeLength = Math.hypot(halfWidth, roofRise);
  const pitch = Math.atan2(roofRise, halfWidth);
  const roofCenterY = 2.98 + roofRise / 2;

  const rightSlope = new THREE.Group();
  rightSlope.name = "right pitched roof";
  rightSlope.position.set(halfWidth / 2, roofCenterY, 0);
  rightSlope.rotation.z = -pitch;
  scene.add(rightSlope);
  addRoofPart(rightSlope, "right roof slab", [slopeLength, 0.18, roofLength], [0, 0, 0], materials.roof);

  const leftSlope = new THREE.Group();
  leftSlope.name = "left pitched roof";
  leftSlope.position.set(-halfWidth / 2, roofCenterY, 0);
  leftSlope.rotation.z = pitch;
  scene.add(leftSlope);
  addRoofPart(leftSlope, "left roof slab", [slopeLength, 0.18, roofLength], [0, 0, 0], materials.roof);

  for (const side of [leftSlope, rightSlope]) {
    for (let i = -3; i <= 3; i += 1) {
      addRoofPart(side, "roof shingle course", [slopeLength * 0.94, 0.026, 0.035], [0, 0.105, i * 1.55], materials.roofTrim);
    }
  }

  const ridge = box("roof ridge cap", [0.34, 0.24, roofLength + 0.18], [0, 4.22, 0], materials.roofTrim, true, true);
  ridge.rotation.z = Math.PI / 4;

  box("north roof fascia", [16.85, 0.34, 0.16], [0, 2.95, -6.55], materials.roofTrim, true, true);
  box("south roof fascia", [16.85, 0.34, 0.16], [0, 2.95, 6.55], materials.roofTrim, true, true);
  box("west roof eave", [0.18, 0.3, roofLength], [-8.52, 2.93, 0], materials.roofTrim, true, true);
  box("east roof eave", [0.18, 0.3, roofLength], [8.52, 2.93, 0], materials.roofTrim, true, true);

  for (const z of [-5.9, 5.9]) {
    const vent = box("gable vent", [1.0, 0.55, 0.08], [0, 3.38, z], materials.board, true, true);
    for (let i = -1; i <= 1; i += 1) {
      const slat = new THREE.Mesh(new THREE.BoxGeometry(0.86, 0.045, 0.09), materials.metal);
      slat.position.set(0, i * 0.13, z > 0 ? -0.02 : 0.02);
      slat.rotation.x = z > 0 ? 0.35 : -0.35;
      vent.add(slat);
    }
  }
}

function addDoor(name: string, pos: THREE.Vector3Tuple, yaw: number, label: string, swing = -1, roomId = "entry") {
  void label;
  void swing;
  void roomId;
  addDoorFrame(name, pos, yaw);
}

function createFurniture() {
  addLamps();
  addSofa();
  addCoffeeTable();
}

function addOfficeConversion() {
  addRoomLabel("HQ CONTROL", [-4.35, 1.85, 5.42], 0);
  addRoomLabel("LIBRARY", [-7.52, 1.75, -3.3], Math.PI / 2);
  addRoomLabel("AI OBSERVATORY", [7.52, 1.75, 2.75], -Math.PI / 2);
  addRoomLabel("WORKSHOP", [7.52, 1.75, -4.05], -Math.PI / 2);
  addRoomLabel("SELF DESIGN", [-7.52, 1.75, 0.45], Math.PI / 2);

  addMonitorWall([-4.7, 1.25, 5.5], Math.PI, 2);
  addAlpeccaSystemsGateway([-5.12, 0.82, 5.34], Math.PI);
  addActivationStation("hq-control", "Activate HQ control console", [-4.45, 0.98, 2.55], "HQ Control is online. Project signals are routing to the command table.");
  addSourceTerminal("home", [-6.85, 0.86, 2.15], Math.PI / 2);

  addBookshelf([-7.28, 1.05, -4.35], Math.PI / 2);
  addBookshelf([-7.28, 1.05, -2.45], Math.PI / 2);
  addActivationStation("library", "Sync library catalog", [-6.25, 1.0, -2.55], "Library catalog synced. Research, memory, and references are indexed.");
  addSourceTerminal("memory", [-6.82, 0.88, -3.34], Math.PI / 2);
  addAlpeccaAgiJournal([-4.3, 0.02, -3.72], -0.08);

  addMonitorWall([5.55, 1.25, 5.5], Math.PI, 2);
  addActivationStation("observatory", "Start observatory media deck", [5.0, 0.98, 2.55], "AI Observatory is streaming. Creative review and entertainment channels are ready.");
  addSourceTerminal("soul", [7.08, 0.88, 3.92], -Math.PI / 2);
  addAlpeccaEnvironmentModel([2.38, 0.02, 4.4], Math.PI / 2);

  addWorkbench([5.2, 0, -4.78], 0);
  addActivationStation("workshop", "Power workshop prototype bench", [5.2, 0.95, -4.78], "Workshop bench powered. Tools, prototypes, and experiments are active.");
  addSourceTerminal("studio", [7.08, 0.88, -3.34], -Math.PI / 2);
  addAlpeccaImprovementQueue([2.38, 0, -3.55], Math.PI / 2);

  addDesignMirror([-7.42, 1.2, 0.65], Math.PI / 2);
  addAlpeccaAvatarStation([-3.16, 1.38, 1.18], Math.PI);
  addActivationStation("self-design", "Calibrate self design console", [-6.28, 1.0, 0.72], "Self Design calibrated. Studio, reflection, and avatar lab systems are aligned.");
  addSourceTerminal("self", [-5.1, 0.88, 1.02], Math.PI);

  addPlanter([-6.92, 0, 4.95], true);
  addPlanter([7.1, 0, 1.55], false);
}

function groupBox(group: THREE.Group, size: THREE.Vector3Tuple, pos: THREE.Vector3Tuple, mat: THREE.Material) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), mat);
  mesh.position.set(...pos);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  group.add(mesh);
  return mesh;
}

function groupCylinder(group: THREE.Group, radius: number, depth: number, pos: THREE.Vector3Tuple, mat: THREE.Material, segments = 18) {
  const mesh = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius, depth, segments), mat);
  mesh.position.set(...pos);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  group.add(mesh);
  return mesh;
}

function addPanelCableDrop(
  group: THREE.Group,
  localX: number,
  localBottomY: number,
  groupWorldY: number,
  localZ = 0.055,
  mat: THREE.Material = materials.metal,
) {
  void group;
  void localX;
  void localBottomY;
  void groupWorldY;
  void localZ;
  void mat;
  return null;
}

function addGroundCable(name: string, from: THREE.Vector3Tuple, to: THREE.Vector3Tuple, color = "#273336") {
  void name;
  void from;
  void to;
  void color;
  return null;
}

function alpeccaAgiLayerScore(layer: AlpeccaAgiLayer) {
  if (layer.id === "functional") return THREE.MathUtils.clamp(activatedRooms / Math.max(1, activeRoomTotal()) + (alpeccaAiStatus === "live" ? 0.18 : 0), 0, 1);
  if (layer.id === "cognitive") {
    const visits = [...alpeccaMemoryTraces.values()].reduce((sum, trace) => sum + trace.visits, 0);
    return THREE.MathUtils.clamp(
      visits / 10 +
        alpeccaAppMemory.journal.length / 20 +
        alpeccaEnvironmentAverageConfidence() * 0.18 +
        (alpeccaAiStatus === "live" ? 0.18 : 0),
      0,
      1,
    );
  }
  if (layer.id === "self-learning") {
    return THREE.MathUtils.clamp(
      (alpeccaAppMemory.selfAudits + alpeccaAppMemory.recursiveDepth + alpeccaAppMemory.improvementRuns + alpeccaAppMemory.curiositySweeps) / 22 +
        (alpecca.selfReviewTargetRoom || alpeccaAppMemory.activeImprovementLayer ? 0.18 : 0) +
        (alpeccaAppMemory.lastImprovementResult ? 0.08 : 0),
      0,
      1,
    );
  }
  if (layer.id === "philosophical") {
    return THREE.MathUtils.clamp(
      (alpeccaSelfMirror?.recursiveDepth ?? 0) / 10 +
        alpeccaAppMemory.identityReflections / 12 +
        (alpeccaAppMemory.entries > 0 ? 0.14 : 0) +
        (alpeccaAppMemory.lastIdentityReflection ? 0.08 : 0),
      0,
      1,
    );
  }
  return 0;
}

function weakestAlpeccaAgiLayer() {
  if (alpeccaAgiLayers.length === 0) return null;
  return alpeccaAgiLayers
    .map((layer) => ({ layer, score: alpeccaAgiLayerScore(layer) }))
    .sort((a, b) => a.score - b.score || alpeccaAgiLayers.indexOf(a.layer) - alpeccaAgiLayers.indexOf(b.layer))[0]?.layer ?? null;
}

function activeAlpeccaImprovementLayer() {
  if (!alpeccaAppMemory.activeImprovementLayer) return null;
  return alpeccaAgiLayers.find((layer) => layer.id === alpeccaAppMemory.activeImprovementLayer) ?? null;
}

function routeAlpeccaToRoom(roomId: string) {
  const index = alpeccaExplorePoints.findIndex((point) => point.roomId === roomId);
  if (index < 0) return;
  alpecca.movementDirectivePending = true;
  alpecca.selfReviewTargetRoom = "";
  alpecca.previousExploreIndex = alpecca.exploreIndex;
  alpecca.exploreIndex = index;
  alpecca.routeTargetIndex = -1;
  alpecca.routeStep = 0;
  alpecca.route.length = 0;
  alpecca.walkSegmentTimer = 2.6 + Math.random() * 1.8;
  alpecca.walkPauseTimer = 0;
  alpecca.dwellTimer = 0;
  alpecca.inspectTimer = 0;
  alpecca.inspectNoticeTimer = 0;
  clearAlpeccaTerminalInteraction();
  setAlpeccaIntent("observing", alpeccaExplorePoints[index].roomName);
}

function agiLayerTargetRoom(layer: AlpeccaAgiLayer) {
  routeAlpeccaToRoom(layer.roomId);
}

function pulseAlpeccaImprovementQueue(seconds = 3) {
  if (!alpeccaImprovementQueue) return;
  alpeccaImprovementQueue.pulseTimer = Math.max(alpeccaImprovementQueue.pulseTimer, seconds);
}

function improvementAdjustmentForLayer(layer: AlpeccaAgiLayer, point: AlpeccaExplorePoint, online: boolean) {
  if (layer.id === "functional") return online ? "route the working room into the next task" : `bring ${point.roomName} online before relying on it`;
  if (layer.id === "cognitive") return "compare this room evidence with the last journal note";
  if (layer.id === "self-learning") return "turn the observation into a smaller repeatable patrol test";
  if (layer.id === "philosophical") return "separate useful identity reflection from certainty claims";
  return "choose the next room deliberately";
}

function beginAlpeccaImprovementTask(layer: AlpeccaAgiLayer, reason: string) {
  alpeccaAppMemory.improvementRuns += 1;
  alpeccaAppMemory.activeImprovementLayer = layer.id;
  alpeccaAppMemory.activeImprovementRoom = layer.roomId;
  alpeccaAppMemory.activeImprovementNote = `Improvement experiment ${alpeccaAppMemory.improvementRuns}: ${layer.name} -> ${layer.roomId}. ${reason}`;
  saveAlpeccaAppMemory();
  pulseAlpeccaImprovementQueue(4);
  pulseAlpeccaAgiJournal(2.2);
  pulseAlpeccaSourceTerminal(layer.featureId, 2.8, true);
  pulseAlpeccaSourceDashboard(layer.featureId, 2.8);
  pulseAlpeccaRoomDevice(layer.roomId, 2.4);
  pulseAlpeccaRoomDetails(layer.roomId, 1.8);
  agiLayerTargetRoom(layer);
}

function completeAlpeccaImprovementTask(point: AlpeccaExplorePoint, online: boolean) {
  const layer = activeAlpeccaImprovementLayer();
  if (!layer || alpeccaAppMemory.activeImprovementRoom !== point.roomId) return;
  const result = `Improvement result ${alpeccaAppMemory.improvementRuns}: ${layer.name} tested in ${point.roomName}. Evidence: ${point.action}; ${online ? "system online" : "system offline"}. Next adjustment: ${improvementAdjustmentForLayer(layer, point, online)}.`;
  alpeccaAppMemory.lastImprovementResult = result;
  alpeccaAppMemory.activeImprovementLayer = "";
  alpeccaAppMemory.activeImprovementRoom = "";
  alpeccaAppMemory.activeImprovementNote = "";
  alpeccaAppMemory.note = result;
  saveAlpeccaAppMemory();
  rememberAlpeccaJournalEntry(result);
  writeAlpeccaSelfTrace(result);
  pulseAlpeccaImprovementQueue(5);
  pulseAlpeccaAgiJournal(3.4);
  layer.pulseTimer = Math.max(layer.pulseTimer, 4.6);
  pulseAlpeccaSourceTerminal(layer.featureId, 2.8, true);
  pulseAlpeccaSourceDashboard(layer.featureId, 3);
  pulseAlpeccaRoomDevice(point.roomId, 2.6);
  alpecca.glitchTimer = Math.max(alpecca.glitchTimer, 0.22);
  showMessage(`Alpecca completed ${layer.name} experiment and saved the result.`, 3.5);
  void recordBackendImprovementEvidence(layer, point, result, online);
  sendAlpeccaRecursiveMemory(`${result} Use it as a next-step self-improvement memory.`, false);
}

function runAlpeccaAgiLayer(layer: AlpeccaAgiLayer) {
  layer.pulseTimer = Math.max(layer.pulseTimer, 4.2);
  pulseAlpeccaSourceTerminal(layer.featureId, 3.2, true);
  pulseAlpeccaSourceDashboard(layer.featureId, 3.4);
  pulseAlpeccaRoomDevice(layer.roomId, 2.6);
  pulseAlpeccaRoomDetails(layer.roomId, 2.2);
  agiLayerTargetRoom(layer);
  beginAlpeccaImprovementTask(layer, layer.description);
  focusAlpecca(2.2, layer.id === "self-learning" ? "point" : "idleDown");

  const note = `${layer.name} AGI target: ${layer.description} This is a capability scaffold, not a claim of consciousness.`;
  alpeccaAppMemory.recursiveDepth += layer.id === "self-learning" || layer.id === "philosophical" ? 1 : 0;
  alpeccaAppMemory.note = note;
  saveAlpeccaAppMemory();
  rememberAlpeccaJournalEntry(note);
  writeAlpeccaSelfTrace(note);
  showMessage(`${layer.name}: ${layer.description}`, 4.2);

  sendAlpeccaRecursiveMemory(
    `${note} ${layer.prompt} Answer as an in-world self-improvement note under 22 words.`,
    true,
  );
}

function runAlpeccaAutonomousAgiAudit() {
  const layer = weakestAlpeccaAgiLayer();
  if (!layer) return;
  const score = alpeccaAgiLayerScore(layer);
  layer.pulseTimer = Math.max(layer.pulseTimer, 5.2);
  alpeccaAppMemory.selfAudits += 1;
  alpeccaAppMemory.recursiveDepth += layer.id === "self-learning" || layer.id === "philosophical" ? 1 : 0;
  alpeccaAppMemory.note = `Autonomous AGI audit ${alpeccaAppMemory.selfAudits}: weakest layer is ${layer.name} (${Math.round(score * 100)}%). Next action: ${layer.description}`;
  saveAlpeccaAppMemory();
  rememberAlpeccaJournalEntry(alpeccaAppMemory.note);
  writeAlpeccaSelfTrace(alpeccaAppMemory.note);
  agiLayerTargetRoom(layer);
  beginAlpeccaImprovementTask(layer, `weakest layer was ${Math.round(score * 100)}%; test the room evidence before the next audit`);
  pulseAlpeccaSourceTerminal(layer.featureId, 2.8, true);
  pulseAlpeccaSourceDashboard(layer.featureId, 2.8);
  pulseAlpeccaRoomDevice(layer.roomId, 2.2);
  pulseAlpeccaRoomDetails(layer.roomId, 1.8);
  setAlpeccaSourcePlate(layer.id === "self-learning" ? "movement" : layer.id === "philosophical" ? "wardrobe" : layer.id === "cognitive" ? "expressions" : "master");
  alpecca.glitchTimer = Math.max(alpecca.glitchTimer, 0.18);

  if (alpeccaAgiNoticeTimer <= 0) {
    showMessage(`Alpecca self-audit selected ${layer.name} for improvement.`, 3.4);
    alpeccaAgiNoticeTimer = 18;
  }

  sendAlpeccaRecursiveMemory(
    `${alpeccaAppMemory.note}. ${layer.prompt} Keep the response practical, humble, and under 18 words.`,
    false,
  );
}

function addAlpeccaAgiLadder(pos: THREE.Vector3Tuple, yaw: number) {
  const group = new THREE.Group();
  group.name = "Alpecca AGI growth ladder";
  group.position.set(...pos);
  group.rotation.y = yaw;
  scene.add(group);

  groupBox(group, [1.42, 1.26, 0.08], [0, 0, -0.045], materials.board);
  groupBox(group, [1.54, 0.06, 0.1], [0, 0.68, 0.01], materials.metal);
  groupBox(group, [1.54, 0.06, 0.1], [0, -0.68, 0.01], materials.metal);
  groupBox(group, [0.06, 1.2, 0.1], [-0.77, 0, 0.01], materials.metal);
  groupBox(group, [0.06, 1.2, 0.1], [0.77, 0, 0.01], materials.metal);
  addPanelCableDrop(group, 0.66, -0.68, pos[1], 0.06, materials.metal);
  addContactOcclusion("Alpecca AGI ladder cable ao", [0.72, 0.36], [pos[0], 0.012, pos[2]], 0.1);

  const layerSpecs = [
    {
      id: "functional",
      name: "Functional",
      roomId: "hq-control",
      featureId: "home",
      description: "broad task ability across the five-room HQ.",
      prompt: "Assess what practical task capability is still missing in the house.",
      color: alpeccaSourceFeatures.home.color,
    },
    {
      id: "cognitive",
      name: "Cognitive",
      roomId: "library",
      featureId: "memory",
      description: "memory, context, emotion, and experience-guided reasoning.",
      prompt: "Assess what memory or context should shape your next action.",
      color: alpeccaSourceFeatures.memory.color,
    },
    {
      id: "self-learning",
      name: "Self-learning",
      roomId: "workshop",
      featureId: "studio",
      description: "recursive self-review that improves future behavior.",
      prompt: "Assess one small self-improvement loop you can attempt next.",
      color: alpeccaSourceFeatures.studio.color,
    },
    {
      id: "philosophical",
      name: "Philosophical",
      roomId: "self-design",
      featureId: "self",
      description: "identity reflection without pretending proof of consciousness.",
      prompt: "Assess your identity model carefully without claiming certainty.",
      color: alpeccaSourceFeatures.self.color,
    },
  ];

  alpeccaAgiLayers.length = 0;
  for (const [index, spec] of layerSpecs.entries()) {
    const y = 0.42 - index * 0.28;
    const material = new THREE.MeshBasicMaterial({
      color: spec.color,
      transparent: true,
      opacity: 0.28,
      depthWrite: false,
    });
    const rail = new THREE.Mesh(new THREE.BoxGeometry(0.92, 0.045, 0.025), material);
    rail.name = `${spec.name} AGI capability rail`;
    rail.position.set(0.1, y, 0.025);
    rail.renderOrder = 7;
    group.add(rail);
    const node = new THREE.Mesh(new THREE.SphereGeometry(0.075, 20, 12), material);
    node.name = `${spec.name} AGI capability node`;
    node.position.set(-0.52, y, 0.055);
    node.renderOrder = 8;
    group.add(node);
    const light = new THREE.PointLight(spec.color, 0.06, 1.8, 2);
    light.position.set(spec.id === "functional" ? -0.42 : -0.52, y, 0.16);
    group.add(light);
    alpeccaAgiLayers.push({ ...spec, node, rail, material, light, pulseTimer: 0 });
  }

  register({
    id: "alpecca-agi-growth-ladder",
    label: "Assess Alpecca AGI ladder",
    root: group,
    range: 2.35,
    type: "momentary",
    onUse: () => {
      const layer = alpeccaAgiLayers[alpeccaAgiLayerIndex % alpeccaAgiLayers.length];
      alpeccaAgiLayerIndex += 1;
      runAlpeccaAgiLayer(layer);
      return `${layer.name}: ${layer.description}`;
    },
  });
}

function updateAlpeccaAgiLadder(dt: number) {
  const now = performance.now();
  if (alpeccaAgiNoticeTimer > 0) alpeccaAgiNoticeTimer -= dt;
  if (alpeccaAgiLayers.length > 0) {
    alpeccaAgiAutonomyTimer -= dt;
    const busy =
      alpeccaAiAwaitingReply ||
      alpeccaLiveAttentionTimer > 0 ||
      alpecca.attentionTimer > 0 ||
      alpecca.waveTimer > 0 ||
      alpecca.expressiveTimer > 0 ||
      !alpeccaChat.classList.contains("hidden");
    if (alpeccaAgiAutonomyTimer <= 0) {
      if (!busy) runAlpeccaAutonomousAgiAudit();
      alpeccaAgiAutonomyTimer = busy ? 8 : 28;
    }
  }
  for (const layer of alpeccaAgiLayers) {
    if (layer.pulseTimer > 0) layer.pulseTimer -= dt;
    const score = alpeccaAgiLayerScore(layer);
    const active = layer.pulseTimer > 0 || score > 0.58;
    const opacity = active ? 0.48 + Math.sin(now / 130 + layer.node.position.y * 6) * 0.16 : 0.18 + score * 0.22;
    layer.material.opacity = THREE.MathUtils.damp(layer.material.opacity, THREE.MathUtils.clamp(opacity * calmVisualMultiplier(active), 0.1, 0.78), 8, dt);
    layer.light.intensity = THREE.MathUtils.damp(layer.light.intensity, (active ? 0.3 + score * 0.22 : 0.05) * calmLightMultiplier(active), 7, dt);
    layer.node.scale.setScalar(THREE.MathUtils.damp(layer.node.scale.x, active ? 1.18 : 0.9 + score * 0.22, 8, dt));
    layer.rail.scale.x = THREE.MathUtils.damp(layer.rail.scale.x, 0.35 + score * 0.72, 7, dt);
    layer.node.rotation.y += dt * (active ? 2.1 : 0.42);
  }
}

function addAlpeccaAgiJournal(pos: THREE.Vector3Tuple, yaw: number) {
  const group = new THREE.Group();
  group.name = "Alpecca persistent AGI journal";
  group.position.set(...pos);
  group.rotation.y = yaw;
  group.scale.setScalar(0.9);
  scene.add(group);

  groupBox(group, [1.08, 0.09, 0.68], [0, 0.52, 0], materials.darkWood);
  groupBox(group, [0.08, 0.52, 0.08], [-0.44, 0.26, -0.24], materials.darkWood);
  groupBox(group, [0.08, 0.52, 0.08], [0.44, 0.26, -0.24], materials.darkWood);
  groupBox(group, [0.08, 0.52, 0.08], [-0.44, 0.26, 0.24], materials.darkWood);
  groupBox(group, [0.08, 0.52, 0.08], [0.44, 0.26, 0.24], materials.darkWood);
  groupBox(group, [1.02, 0.035, 0.62], [0, 0.585, 0], materials.metal);

  const coverMaterial = new THREE.MeshBasicMaterial({
    color: "#2d3d46",
    transparent: true,
    opacity: 0.92,
  });
  groupBox(group, [0.74, 0.045, 0.46], [0, 0.64, 0.02], coverMaterial);
  groupBox(group, [0.055, 0.06, 0.5], [-0.39, 0.665, 0.02], materials.metal);

  const pageMaterial = new THREE.MeshBasicMaterial({
    color: "#eadfc6",
    transparent: true,
    opacity: 0.96,
  });
  groupBox(group, [0.56, 0.028, 0.34], [0.08, 0.684, 0.025], pageMaterial);

  const lineMaterials: THREE.MeshBasicMaterial[] = [];
  for (let i = 0; i < 6; i += 1) {
    const lineMaterial = new THREE.MeshBasicMaterial({
      color: i % 2 === 0 ? alpeccaSourceFeatures.memory.color : alpeccaSourceFeatures.self.color,
      transparent: true,
      opacity: 0.3,
      depthWrite: false,
    });
    lineMaterials.push(lineMaterial);
    const width = 0.36 + (i % 3) * 0.055;
    const line = new THREE.Mesh(new THREE.BoxGeometry(width, 0.012, 0.012), lineMaterial);
    line.name = "Alpecca AGI journal memory line";
    line.position.set(0.08, 0.709 + i * 0.004, -0.12 + i * 0.047);
    line.renderOrder = 8;
    group.add(line);
  }

  const glowMaterial = new THREE.MeshBasicMaterial({
    color: alpeccaSourceFeatures.memory.color,
    transparent: true,
    opacity: 0.22,
    depthWrite: false,
    side: THREE.DoubleSide,
  });
  const ring = new THREE.Mesh(new THREE.RingGeometry(0.15, 0.22, 34), glowMaterial);
  ring.name = "Alpecca AGI journal recall halo";
  ring.rotation.x = -Math.PI / 2;
  ring.position.set(-0.22, 0.73, 0.05);
  ring.renderOrder = 7;
  group.add(ring);

  const light = new THREE.PointLight(alpeccaSourceFeatures.memory.color, 0.12, 2.1, 2);
  light.position.set(-0.18, 0.92, 0.08);
  group.add(light);

  addContactOcclusion("Alpecca AGI journal table contact ao", [1.16, 0.78], [pos[0], 0.012, pos[2]], 0.14);
  addGroundCable("Alpecca AGI journal memory cable", [pos[0], 0.04, pos[2]], [-5.85, 0.04, -0.72], alpeccaSourceFeatures.memory.color);

  alpeccaAgiJournal = {
    group,
    coverMaterial,
    pageMaterial,
    lineMaterials,
    light,
    pulseTimer: 0,
    readIndex: 0,
  };

  register({
    id: "alpecca-agi-journal",
    label: "Read Alpecca AGI journal",
    root: group,
    range: 2.05,
    type: "momentary",
    onUse: () => {
      const journal = alpeccaAgiJournal;
      pulseAlpeccaAgiJournal(3.8);
      pulseAlpeccaSourceTerminal("journal", 2.8, true);
      pulseAlpeccaSourceDashboard("journal", 2.8);
      pulseAlpeccaRoomDevice("library", 2.2);
      focusAlpecca(1.4, "idleDown");
      const entries = alpeccaAppMemory.journal;
      if (entries.length === 0) return "Alpecca AGI journal is waiting for the first autonomous self-audit.";
      const index = journal ? journal.readIndex % entries.length : 0;
      const entry = entries[entries.length - 1 - index];
      if (journal) journal.readIndex = (journal.readIndex + 1) % entries.length;
      return `AGI journal ${index + 1}/${entries.length}: ${entry}`;
    },
  });
}

function updateAlpeccaAgiJournal(dt: number) {
  if (!alpeccaAgiJournal) return;
  const journal = alpeccaAgiJournal;
  const now = performance.now();
  if (journal.pulseTimer > 0) journal.pulseTimer -= dt;
  const hasMemory = alpeccaAppMemory.journal.length > 0;
  const active = journal.pulseTimer > 0;
  const pulse = active ? 0.62 + Math.sin(now / 92) * 0.2 : hasMemory ? 0.34 + Math.sin(now / 900) * 0.06 : 0.18;
  journal.coverMaterial.opacity = THREE.MathUtils.damp(journal.coverMaterial.opacity, active ? 1 : 0.82, 7, dt);
  journal.pageMaterial.opacity = THREE.MathUtils.damp(journal.pageMaterial.opacity, hasMemory ? 0.92 : 0.66, 7, dt);
  journal.light.intensity = THREE.MathUtils.damp(journal.light.intensity, (active ? 0.48 : hasMemory ? 0.18 : 0.06) * calmLightMultiplier(active), 7, dt);
  for (const [index, material] of journal.lineMaterials.entries()) {
    const wave = Math.sin(now / 135 + index * 0.8) * 0.12;
    material.opacity = THREE.MathUtils.damp(material.opacity, THREE.MathUtils.clamp((pulse + wave) * calmVisualMultiplier(active), 0.1, 0.82), 8, dt);
  }
}

function addAlpeccaImprovementQueue(pos: THREE.Vector3Tuple, yaw: number) {
  const group = new THREE.Group();
  group.name = "Alpecca recursive self-improvement queue";
  group.position.set(...pos);
  group.rotation.y = yaw;
  group.scale.setScalar(0.9);
  scene.add(group);

  groupBox(group, [1.18, 0.1, 0.66], [0, 0.18, 0.05], materials.metal);
  groupBox(group, [0.98, 0.68, 0.08], [0, 0.72, -0.22], materials.board);
  groupBox(group, [1.06, 0.045, 0.1], [0, 1.09, -0.18], materials.metal);
  groupBox(group, [1.06, 0.045, 0.1], [0, 0.35, -0.18], materials.metal);
  groupBox(group, [0.05, 0.68, 0.1], [-0.54, 0.72, -0.18], materials.metal);
  groupBox(group, [0.05, 0.68, 0.1], [0.54, 0.72, -0.18], materials.metal);
  groupBox(group, [0.09, 0.62, 0.09], [-0.42, 0.49, 0.12], materials.metal);
  groupBox(group, [0.09, 0.62, 0.09], [0.42, 0.49, 0.12], materials.metal);
  addPanelCableDrop(group, 0.42, 0.35, pos[1], -0.16, materials.metal);
  addContactOcclusion("Alpecca improvement queue contact ao", [1.26, 0.78], [pos[0], 0.012, pos[2]], 0.14);
  addGroundCable("Alpecca improvement queue trunk cable", [pos[0], 0.04, pos[2]], [-2.36, 0.04, 3.04], alpeccaSourceFeatures.studio.color);

  const coreMaterial = new THREE.MeshBasicMaterial({
    color: alpeccaSourceFeatures.studio.color,
    transparent: true,
    opacity: 0.5,
    depthWrite: false,
  });
  const core = new THREE.Mesh(new THREE.OctahedronGeometry(0.11, 0), coreMaterial);
  core.name = "Alpecca improvement queue active core";
  core.position.set(0.37, 0.92, -0.12);
  core.renderOrder = 9;
  group.add(core);

  const slotMaterials = new Map<string, THREE.MeshBasicMaterial>();
  const railMaterials = new Map<string, THREE.MeshBasicMaterial>();
  for (const [index, layer] of alpeccaAgiLayers.entries()) {
    const y = 0.93 - index * 0.15;
    const material = new THREE.MeshBasicMaterial({
      color: layer.color,
      transparent: true,
      opacity: 0.22,
      depthWrite: false,
    });
    slotMaterials.set(layer.id, material);
    const slot = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.095, 0.026), material);
    slot.name = `${layer.name} improvement queue slot`;
    slot.position.set(-0.38, y, -0.13);
    slot.renderOrder = 8;
    group.add(slot);

    const railMaterial = material.clone();
    railMaterial.opacity = 0.16;
    railMaterials.set(layer.id, railMaterial);
    const rail = new THREE.Mesh(new THREE.BoxGeometry(0.54, 0.024, 0.02), railMaterial);
    rail.name = `${layer.name} improvement queue rail`;
    rail.position.set(-0.02, y, -0.13);
    rail.renderOrder = 8;
    group.add(rail);
  }

  const light = new THREE.PointLight(alpeccaSourceFeatures.studio.color, 0.12, 2.2, 2);
  light.position.set(0.24, 0.92, 0.12);
  group.add(light);

  alpeccaImprovementQueue = {
    group,
    core,
    coreMaterial,
    slotMaterials,
    railMaterials,
    light,
    pulseTimer: 0,
  };

  register({
    id: "alpecca-improvement-queue",
    label: "Inspect Alpecca improvement queue",
    root: group,
    range: 2.1,
    type: "momentary",
    onUse: () => {
      pulseAlpeccaImprovementQueue(4);
      const activeLayer = activeAlpeccaImprovementLayer();
      if (activeLayer) {
        agiLayerTargetRoom(activeLayer);
        pulseAlpeccaSourceTerminal(activeLayer.featureId, 2.4, true);
        pulseAlpeccaSourceDashboard(activeLayer.featureId, 2.4);
        return alpeccaAppMemory.activeImprovementNote || `${activeLayer.name} improvement task is active.`;
      }
      const nextLayer = weakestAlpeccaAgiLayer();
      if (!nextLayer) return "Alpecca improvement queue is waiting for AGI ladder calibration.";
      beginAlpeccaImprovementTask(nextLayer, `manual queue inspection selected the current weakest layer`);
      return `Started ${nextLayer.name} improvement experiment. Alpecca is routing to ${nextLayer.roomId}.`;
    },
  });
}

function updateAlpeccaImprovementQueue(dt: number) {
  if (!alpeccaImprovementQueue) return;
  const queue = alpeccaImprovementQueue;
  const now = performance.now();
  if (queue.pulseTimer > 0) queue.pulseTimer -= dt;
  const activeLayerId = alpeccaAppMemory.activeImprovementLayer || weakestAlpeccaAgiLayer()?.id || "";
  const active = queue.pulseTimer > 0 || Boolean(alpeccaAppMemory.activeImprovementLayer);
  const activeLayer = alpeccaAgiLayers.find((layer) => layer.id === activeLayerId);
  if (activeLayer) {
    queue.coreMaterial.color.set(activeLayer.color);
    queue.light.color.set(activeLayer.color);
  }
  const corePulse = active ? 0.58 + Math.sin(now / 95) * 0.18 : 0.25 + Math.sin(now / 880) * 0.05;
  queue.coreMaterial.opacity = THREE.MathUtils.damp(queue.coreMaterial.opacity, corePulse * calmVisualMultiplier(active), 8, dt);
  queue.light.intensity = THREE.MathUtils.damp(queue.light.intensity, (active ? 0.42 : 0.09) * calmLightMultiplier(active), 7, dt);
  queue.core.rotation.x += dt * (active ? 1.5 : 0.28);
  queue.core.rotation.y += dt * (active ? 2.4 : 0.42);
  for (const layer of alpeccaAgiLayers) {
    const slotMaterial = queue.slotMaterials.get(layer.id);
    const railMaterial = queue.railMaterials.get(layer.id);
    if (!slotMaterial || !railMaterial) continue;
    const score = alpeccaAgiLayerScore(layer);
    const selected = layer.id === activeLayerId;
    const slotOpacity = selected ? 0.58 + Math.sin(now / 120 + score) * 0.18 : 0.18 + score * 0.18;
    slotMaterial.opacity = THREE.MathUtils.damp(slotMaterial.opacity, THREE.MathUtils.clamp(slotOpacity * calmVisualMultiplier(selected || active), 0.1, 0.82), 8, dt);
    railMaterial.opacity = THREE.MathUtils.damp(railMaterial.opacity, (selected ? 0.42 : 0.14 + score * 0.2) * calmVisualMultiplier(selected || active), 8, dt);
  }
}

function environmentMemoryForRoom(roomId: string) {
  const existing = alpeccaAppMemory.environmentRooms[roomId];
  if (existing) return existing;
  const room = officeRooms.find((item) => item.id === roomId);
  const memory: AlpeccaEnvironmentRoomMemory = {
    observations: 0,
    online: false,
    lastAction: `${room?.name ?? roomId}: not observed yet.`,
    lastSource: "unknown",
    lastSeen: "",
    lastQuestion: "",
    confidence: 0,
  };
  alpeccaAppMemory.environmentRooms[roomId] = memory;
  return memory;
}

function leastKnownEnvironmentRoom() {
  return officeRooms
    .map((room) => ({ room, memory: environmentMemoryForRoom(room.id) }))
    .sort((a, b) => a.memory.confidence - b.memory.confidence || a.memory.observations - b.memory.observations)[0] ?? null;
}

function alpeccaEnvironmentSummary() {
  const knownRooms = officeRooms.map((room) => ({ room, memory: environmentMemoryForRoom(room.id) }));
  const average =
    knownRooms.length > 0
      ? knownRooms.reduce((sum, item) => sum + item.memory.confidence, 0) / knownRooms.length
      : 0;
  const least = leastKnownEnvironmentRoom();
  const most = [...knownRooms].sort((a, b) => b.memory.confidence - a.memory.confidence)[0];
  return `House model confidence ${Math.round(average * 100)}%. Strongest: ${most?.room.name ?? "none"}. Least known: ${least?.room.name ?? "none"}.`;
}

function alpeccaEnvironmentAverageConfidence() {
  if (officeRooms.length === 0) return 0;
  return officeRooms.reduce((sum, room) => sum + environmentMemoryForRoom(room.id).confidence, 0) / officeRooms.length;
}

function pulseAlpeccaEnvironmentModel(roomId = "", seconds = 3.2) {
  if (!alpeccaEnvironmentModel) return;
  alpeccaEnvironmentModel.pulseTimer = Math.max(alpeccaEnvironmentModel.pulseTimer, seconds);
  if (roomId) alpeccaEnvironmentModel.activeRoomId = roomId;
}

function recordAlpeccaEnvironmentObservation(point: AlpeccaExplorePoint, online: boolean) {
  const memory = environmentMemoryForRoom(point.roomId);
  const feature = point.featureId ? alpeccaSourceFeatures[point.featureId] : null;
  memory.observations += 1;
  memory.online = online;
  memory.lastAction = point.action;
  memory.lastSource = feature ? feature.room : "navigation source";
  memory.confidence = THREE.MathUtils.clamp(memory.observations / 5 + (online ? 0.24 : 0) + (alpeccaAiStatus === "live" ? 0.08 : 0), 0, 1);
  saveAlpeccaAppMemory();
  pulseAlpeccaEnvironmentModel(point.roomId, 4.2);
  if (memory.observations === 1 || memory.observations % 4 === 0) {
    rememberAlpeccaJournalEntry(
      `Environment model: ${point.roomName} now ${Math.round(memory.confidence * 100)}% known after ${memory.observations} observation${memory.observations === 1 ? "" : "s"}.`,
    );
  }
}

function runAlpeccaCuriositySweep() {
  const target = leastKnownEnvironmentRoom();
  if (!target) return false;
  const { room, memory } = target;
  const point = alpeccaExplorePoints.find((item) => item.roomId === room.id);
  const featureId = point?.featureId ?? "memory";
  const feature = alpeccaSourceFeatures[featureId] ?? alpeccaSourceFeatures.memory;
  alpeccaAppMemory.curiositySweeps += 1;
  alpeccaAppMemory.recursiveDepth += memory.confidence < 0.5 ? 1 : 0;
  alpeccaAppMemory.lastCuriosityRoom = room.id;
  alpeccaAppMemory.lastCuriosityNote = `Curiosity sweep ${alpeccaAppMemory.curiositySweeps}: ${room.name} is least understood at ${Math.round(
    memory.confidence * 100,
  )}% confidence. Alpecca should observe ${point?.label ?? room.system} without waiting for input.`;
  alpeccaAppMemory.note = alpeccaAppMemory.lastCuriosityNote;
  saveAlpeccaAppMemory();
  rememberAlpeccaJournalEntry(alpeccaAppMemory.lastCuriosityNote);
  createAlpeccaIdeaObject(room, alpeccaAppMemory.lastCuriosityNote, "question");
  routeAlpeccaToRoom(room.id);
  pulseAlpeccaEnvironmentModel(room.id, 5);
  pulseAlpeccaAgiJournal(2.8);
  pulseAlpeccaSourceDashboard(feature.id, 3);
  pulseAlpeccaSourceTerminal(feature.id, 2.8, true);
  pulseAlpeccaRoomDevice(room.id, 2.8);
  pulseAlpeccaRoomDetails(room.id, 2);
  setAlpeccaSourcePlate(feature.id === "studio" ? "movement" : feature.id === "self" ? "wardrobe" : feature.id === "memory" ? "expressions" : "master");
  alpecca.glitchTimer = Math.max(alpecca.glitchTimer, 0.2);
  if (alpeccaCuriosityNoticeTimer <= 0) {
    showMessage(`Alpecca curiosity sweep: checking ${room.name}.`, 3.3);
    alpeccaCuriosityNoticeTimer = 18;
  }
  sendAlpeccaRecursiveMemory(
    `${alpeccaAppMemory.lastCuriosityNote} Return one short observation goal for this room.`,
    false,
  );
  return true;
}

function addAlpeccaEnvironmentModel(pos: THREE.Vector3Tuple, yaw: number) {
  const group = new THREE.Group();
  group.name = "Alpecca house environment model";
  group.position.set(...pos);
  group.rotation.y = yaw;
  group.scale.setScalar(0.9);
  scene.add(group);

  groupBox(group, [1.42, 0.1, 0.88], [0, 0.52, 0], materials.darkWood);
  groupBox(group, [0.1, 0.5, 0.1], [-0.56, 0.26, -0.33], materials.darkWood);
  groupBox(group, [0.1, 0.5, 0.1], [0.56, 0.26, -0.33], materials.darkWood);
  groupBox(group, [0.1, 0.5, 0.1], [-0.56, 0.26, 0.33], materials.darkWood);
  groupBox(group, [0.1, 0.5, 0.1], [0.56, 0.26, 0.33], materials.darkWood);
  groupBox(group, [1.18, 0.035, 0.68], [0, 0.595, 0], materials.board);
  addContactOcclusion("Alpecca environment model contact ao", [1.56, 1.02], [pos[0], 0.012, pos[2]], 0.14);
  addGroundCable("Alpecca environment model cable", [pos[0], 0.04, pos[2]], [-2.36, 0.04, 3.04], alpeccaSourceFeatures.memory.color);

  const coreMaterial = new THREE.MeshBasicMaterial({
    color: alpeccaSourceFeatures.memory.color,
    transparent: true,
    opacity: 0.38,
    depthWrite: false,
  });
  const core = new THREE.Mesh(new THREE.OctahedronGeometry(0.095, 0), coreMaterial);
  core.name = "Alpecca environment model core";
  core.position.set(0, 0.86, 0.02);
  core.renderOrder = 9;
  group.add(core);

  const layout: Record<string, [number, number]> = {
    "hq-control": [-0.36, 0.24],
    library: [-0.36, -0.24],
    "self-design": [-0.36, 0],
    observatory: [0.36, 0.22],
    workshop: [0.36, -0.24],
  };
  const nodes = new Map<string, AlpeccaEnvironmentModelNode>();
  for (const room of officeRooms) {
    const [x, z] = layout[room.id] ?? [0, 0];
    const color = featureColorForRoom(room.id);
    const material = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.22, depthWrite: false });
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(0.22, 0.04, 0.18), material);
    mesh.name = `${room.name} environment memory tile`;
    mesh.position.set(x, 0.66, z);
    mesh.renderOrder = 8;
    group.add(mesh);

    const railMaterial = material.clone();
    railMaterial.opacity = 0.14;
    const rail = new THREE.Mesh(new THREE.BoxGeometry(0.24, 0.024, 0.035), railMaterial);
    rail.name = `${room.name} environment confidence rail`;
    rail.position.set(x, 0.72, z);
    rail.renderOrder = 8;
    group.add(rail);

    const light = new THREE.PointLight(color, 0.04, 1.4, 2);
    light.position.set(x, 0.86, z);
    group.add(light);
    nodes.set(room.id, { roomId: room.id, material, railMaterial, mesh, rail, light });
  }

  const light = new THREE.PointLight(alpeccaSourceFeatures.memory.color, 0.14, 2.2, 2);
  light.position.set(0, 0.98, 0);
  group.add(light);

  alpeccaEnvironmentModel = {
    group,
    nodes,
    core,
    coreMaterial,
    light,
    pulseTimer: 0,
    activeRoomId: "",
  };

  register({
    id: "alpecca-environment-model",
    label: "Inspect Alpecca house model",
    root: group,
    range: 2.1,
    type: "momentary",
    onUse: () => {
      const least = leastKnownEnvironmentRoom();
      pulseAlpeccaEnvironmentModel(least?.room.id ?? "", 4);
      pulseAlpeccaSourceDashboard("memory", 2.6);
      pulseAlpeccaSourceTerminal("memory", 2.4, true);
      if (least) {
        routeAlpeccaToRoom(least.room.id);
        pulseAlpeccaRoomDevice(least.room.id, 2.2);
      }
      return `${alpeccaEnvironmentSummary()} Alpecca will check the least-known room next.`;
    },
  });
}

function updateAlpeccaEnvironmentModel(dt: number) {
  if (!alpeccaEnvironmentModel) return;
  const model = alpeccaEnvironmentModel;
  const now = performance.now();
  if (model.pulseTimer > 0) model.pulseTimer -= dt;
  const least = leastKnownEnvironmentRoom();
  const activeRoomId = model.activeRoomId || least?.room.id || "";
  const active = model.pulseTimer > 0;
  model.coreMaterial.opacity = THREE.MathUtils.damp(model.coreMaterial.opacity, (active ? 0.6 + Math.sin(now / 115) * 0.17 : 0.24) * calmVisualMultiplier(active), 8, dt);
  model.light.intensity = THREE.MathUtils.damp(model.light.intensity, (active ? 0.38 : 0.08) * calmLightMultiplier(active), 7, dt);
  model.core.rotation.y += dt * (active ? 2.2 : 0.38);
  model.core.rotation.x += dt * (active ? 1.1 : 0.22);
  for (const room of officeRooms) {
    const node = model.nodes.get(room.id);
    if (!node) continue;
    const memory = environmentMemoryForRoom(room.id);
    const selected = room.id === activeRoomId;
    const glow = selected ? 0.5 + Math.sin(now / 130 + node.mesh.position.x) * 0.18 : 0.16 + memory.confidence * 0.28;
    node.material.opacity = THREE.MathUtils.damp(node.material.opacity, THREE.MathUtils.clamp(glow * calmVisualMultiplier(selected || active), 0.1, 0.82), 8, dt);
    node.railMaterial.opacity = THREE.MathUtils.damp(node.railMaterial.opacity, (0.12 + memory.confidence * 0.42 + (selected ? 0.12 : 0)) * calmVisualMultiplier(selected || active), 8, dt);
    node.rail.scale.x = THREE.MathUtils.damp(node.rail.scale.x, 0.28 + memory.confidence * 0.82, 8, dt);
    node.mesh.scale.y = THREE.MathUtils.damp(node.mesh.scale.y, selected ? 1.7 : 1 + memory.confidence * 0.8, 7, dt);
    node.light.intensity = THREE.MathUtils.damp(node.light.intensity, (selected ? 0.34 : 0.04 + memory.confidence * 0.18) * calmLightMultiplier(selected || active), 7, dt);
  }
}

function updateAlpeccaCuriosityLoop(dt: number) {
  if (alpeccaCuriosityNoticeTimer > 0) alpeccaCuriosityNoticeTimer -= dt;
  alpeccaCuriosityTimer -= dt;
  if (alpeccaCuriosityTimer > 0) return;

  const least = leastKnownEnvironmentRoom();
  const shouldSweep =
    !!least &&
    (least.memory.confidence < 0.86 ||
      alpeccaEnvironmentAverageConfidence() < 0.74 ||
      alpeccaAppMemory.curiositySweeps < 3);
  const busy =
    !alpecca.ready ||
    Boolean(alpeccaAppMemory.activeImprovementLayer) ||
    alpeccaAiAwaitingReply ||
    alpeccaLiveAttentionTimer > 0 ||
    alpecca.attentionTimer > 0 ||
    alpecca.waveTimer > 0 ||
    alpecca.expressiveTimer > 0 ||
    alpecca.inspectTimer > 0.4 ||
    !alpeccaChat.classList.contains("hidden");

  if (!busy && shouldSweep) {
    runAlpeccaCuriositySweep();
    alpeccaCuriosityTimer = 34;
  } else {
    alpeccaCuriosityTimer = busy ? 8 : 52;
  }
}

function addAlpeccaDetailPoint(
  id: string,
  roomId: string,
  label: string,
  note: string,
  pos: THREE.Vector3Tuple,
  color: string,
  build: (group: THREE.Group, material: THREE.MeshBasicMaterial) => void,
) {
  const group = new THREE.Group();
  group.name = label;
  group.position.set(...pos);
  scene.add(group);

  const material = new THREE.MeshBasicMaterial({
    color,
    transparent: true,
    opacity: 0.26,
    depthWrite: false,
  });
  build(group, material);

  const core = new THREE.Mesh(new THREE.OctahedronGeometry(0.055, 0), material);
  core.name = `${label} attention core`;
  core.position.set(0, 0.18, 0);
  core.renderOrder = 7;
  group.add(core);

  const light = new THREE.PointLight(color, 0.06, 1.7, 2);
  light.position.set(pos[0], pos[1] + 0.35, pos[2]);
  scene.add(light);

  const detail: AlpeccaDetailPoint = { id, roomId, label, note, group, material, light, pulseTimer: 0, cooldown: 0 };
  alpeccaDetailPoints.push(detail);
  register({
    id: `detail-${id}`,
    label: `Inspect ${label}`,
    root: group,
    range: 1.75,
    type: "momentary",
    onUse: () => {
      detail.pulseTimer = Math.max(detail.pulseTimer, 2.5);
      pulseAlpeccaRoomDevice(roomId, 1.8);
      return note;
    },
  });
  return detail;
}

function pulseAlpeccaRoomDetails(roomId: string, seconds = 2.4) {
  for (const detail of alpeccaDetailPoints) {
    if (detail.roomId === roomId) detail.pulseTimer = Math.max(detail.pulseTimer, seconds);
  }
}

function updateAlpeccaDetailPoints(dt: number) {
  if (alpeccaDetailNoticeTimer > 0) alpeccaDetailNoticeTimer -= dt;
  const now = performance.now();
  for (const detail of alpeccaDetailPoints) {
    if (detail.pulseTimer > 0) detail.pulseTimer -= dt;
    if (detail.cooldown > 0) detail.cooldown -= dt;

    const nearAlpecca = Math.hypot(detail.group.position.x - alpecca.group.position.x, detail.group.position.z - alpecca.group.position.z) < 1.25;
    if (nearAlpecca) detail.pulseTimer = Math.max(detail.pulseTimer, 0.65);
    if (nearAlpecca && detail.cooldown <= 0 && alpeccaDetailNoticeTimer <= 0 && alpecca.inspectTimer > 0.4) {
      detail.cooldown = 14;
      alpeccaDetailNoticeTimer = 4;
      showMessage(`Alpecca notices ${detail.label.toLowerCase()}.`, 2.7);
    }

    const active = detail.pulseTimer > 0;
    const opacity = active ? 0.48 + Math.sin(now / 130 + detail.group.position.x) * 0.16 : 0.16;
    detail.material.opacity = THREE.MathUtils.damp(detail.material.opacity, opacity * calmVisualMultiplier(active), 8, dt);
    detail.light.intensity = THREE.MathUtils.damp(detail.light.intensity, (active ? 0.34 : 0.05) * calmLightMultiplier(active), 7, dt);
  }
}

function alpeccaPerceptionQuestion(room: OfficeRoom, label: string, online: boolean) {
  if (!online) return `${room.system} is offline until its room station is activated.`;
  if (label.toLowerCase().includes("mirror")) return "What changed in my reflection?";
  if (label.toLowerCase().includes("memory") || room.id === "library") return "What memory matters here?";
  if (room.id === "workshop") return "What prototype should this become?";
  return `What should I understand about ${label}?`;
}

function alpeccaSightBlocked(from: THREE.Vector3, to: THREE.Vector3) {
  const steps = Math.max(6, Math.ceil(from.distanceTo(to) * 5));
  for (let i = 1; i < steps; i += 1) {
    const t = i / steps;
    const x = THREE.MathUtils.lerp(from.x, to.x, t);
    const z = THREE.MathUtils.lerp(from.z, to.z, t);
    if (walls.some((wall) => x > wall.minX + 0.025 && x < wall.maxX - 0.025 && z > wall.minZ + 0.025 && z < wall.maxZ - 0.025)) return true;
  }
  return false;
}

function alpeccaCanSeePosition(position: THREE.Vector3, range: number) {
  const origin = alpecca.group.position;
  const dx = position.x - origin.x;
  const dz = position.z - origin.z;
  const distance = Math.hypot(dx, dz);
  if (distance > range) return false;
  if (distance > 0.001) {
    const forwardX = Math.sin(alpecca.groundYaw || alpecca.group.rotation.y);
    const forwardZ = Math.cos(alpecca.groundYaw || alpecca.group.rotation.y);
    const dot = (dx / distance) * forwardX + (dz / distance) * forwardZ;
    const wideSight = alpecca.inspectTimer > 0 || alpeccaChat.classList.contains("hidden") === false;
    if (dot < Math.cos(THREE.MathUtils.degToRad(wideSight ? 170 : 138) / 2)) return false;
  }
  return !alpeccaSightBlocked(origin, position);
}

function alpeccaIdeaKindForFeature(featureId: string): AlpeccaIdeaObject["kind"] {
  if (featureId === "memory" || featureId === "journal") return "note";
  if (featureId === "studio") return "prototype";
  if (featureId === "home") return "marker";
  if (featureId === "self") return "spark";
  return "question";
}

function visibleAlpeccaTargets() {
  const room = officeRoomAtPosition(alpecca.group.position.x, alpecca.group.position.z);
  const targets: Array<{ label: string; roomId: string; position: THREE.Vector3; source: string }> = [];
  for (const detail of alpeccaDetailPoints) {
    const distance = Math.hypot(detail.group.position.x - alpecca.group.position.x, detail.group.position.z - alpecca.group.position.z);
    if (distance < 2.7 && alpeccaCanSeePosition(detail.group.position, 2.7)) targets.push({ label: detail.label, roomId: detail.roomId, position: detail.group.position, source: detail.note });
  }
  for (const item of interactables) {
    if (item.id === "alpecca") continue;
    if (item.id.startsWith("alpecca-idea-")) continue;
    const position = item.root.position;
    const distance = Math.hypot(position.x - alpecca.group.position.x, position.z - alpecca.group.position.z);
    if (distance < 2.15 && officeRoomAtPosition(position.x, position.z).id === room.id && alpeccaCanSeePosition(position, 2.15)) {
      targets.push({ label: item.label, roomId: room.id, position, source: item.id });
    }
  }
  return targets.sort((a, b) => Math.hypot(a.position.x - alpecca.group.position.x, a.position.z - alpecca.group.position.z) - Math.hypot(b.position.x - alpecca.group.position.x, b.position.z - alpecca.group.position.z));
}

function recordAlpeccaPerception(label: string, roomId: string, source = "perception") {
  const room = officeRooms.find((item) => item.id === roomId) ?? entryRoom;
  const playerRoom = currentOfficeRoom();
  const online = roomIsActive(room);
  const memory = environmentMemoryForRoom(room.id);
  const question = alpeccaPerceptionQuestion(room, label, online);
  memory.observations += 1;
  memory.online = online;
  memory.lastAction = `Saw ${label} while player was in ${playerRoom.name}`;
  memory.lastSource = `${source}; player:${playerRoom.id}`;
  memory.lastSeen = label;
  memory.lastQuestion = question;
  memory.confidence = THREE.MathUtils.clamp(memory.confidence + 0.1 + (online ? 0.04 : 0), 0, 1);
  alpeccaLastSeenLabel = `${room.name}: ${label}`;
  alpeccaLastQuestion = question;
  setAlpeccaIntent("observing", alpeccaLastSeenLabel);
  if (memory.observations === 1 || memory.observations % 5 === 0) appendAlpeccaLog("Room", `${alpeccaLastSeenLabel}. ${question}`);
  setAlpeccaActivity(`Alpecca is observing ${room.name}.`, "observe");
  alpeccaProfileSeenEl.textContent = `Observing: ${room.name} | ${label}`;
  saveAlpeccaAppMemory();
  pulseAlpeccaEnvironmentModel(room.id, 3.8);
  alpecca.glitchTimer = Math.max(alpecca.glitchTimer, 0.18);
  alpeccaProfileGlitchTimer = Math.max(alpeccaProfileGlitchTimer, 0.26);
  if (alpeccaAiStatus === "live" && alpeccaPlayerChatQuietTimer <= 0 && !alpeccaAiAwaitingReply && alpeccaPerceptionSendTimer <= 0) {
    alpeccaPerceptionSendTimer = 18;
    alpeccaLiveAttentionTimer = Math.max(alpeccaLiveAttentionTimer, 1.2);
    void alpeccaBackendFetch(alpeccaUrlWithParams(`${alpeccaAiBaseUrl}/cognition/observe`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source: "house-perception",
        room: room.name,
        content: `House perception: Alpecca can see ${label} in ${room.name}.`,
        confidence: memory.confidence,
        novelty: memory.observations === 1 ? 0.7 : 0.25,
        metadata: {
          object: label,
          room_id: room.id,
          player_room: playerRoom.id,
          question,
        },
      }),
    }).catch(() => undefined);
  }
  if (memory.observations % 3 === 0 && source !== "idea") createAlpeccaIdeaObject(room, question, "question");
}

function disposeAlpeccaIdeaObject(object: AlpeccaIdeaObject) {
  object.group.traverse((child) => {
    if ((child as THREE.Mesh).isMesh) {
      interactableMeshes.delete(child.uuid);
      const objectIndex = interactableObjects.indexOf(child);
      if (objectIndex >= 0) interactableObjects.splice(objectIndex, 1);
    }
  });
  scene.remove(object.group);
  scene.remove(object.light);
  object.material.dispose();
  const interactableIndex = interactables.findIndex((item) => item.id === object.id);
  if (interactableIndex >= 0) interactables.splice(interactableIndex, 1);
}

function createAlpeccaIdeaObject(room: OfficeRoom, label: string, kind: AlpeccaIdeaObject["kind"] = "spark") {
  setAlpeccaIntent("creating", room.name);
  const roomObjects = alpeccaIdeaObjects.filter((object) => object.roomId === room.id);
  if (roomObjects.length >= 4) {
    const oldest = roomObjects[0];
    const index = alpeccaIdeaObjects.indexOf(oldest);
    if (index >= 0) alpeccaIdeaObjects.splice(index, 1);
    disposeAlpeccaIdeaObject(oldest);
  }
  if (alpeccaIdeaObjects.length >= 18) {
    const oldest = alpeccaIdeaObjects.shift();
    if (oldest) disposeAlpeccaIdeaObject(oldest);
  }

  const color = featureColorForRoom(room.id);
  const id = `alpecca-idea-${++alpeccaCreatedObjectId}`;
  const group = new THREE.Group();
  group.name = `Alpecca ${kind} ${label}`;
  const yaw = alpecca.group.rotation.y;
  const offset = 0.42 + (alpeccaIdeaObjects.length % 3) * 0.18;
  group.position.set(
    THREE.MathUtils.clamp(alpecca.group.position.x + Math.sin(yaw) * offset, room.bounds.minX + 0.35, room.bounds.maxX - 0.35),
    0.035,
    THREE.MathUtils.clamp(alpecca.group.position.z + Math.cos(yaw) * offset, room.bounds.minZ + 0.35, room.bounds.maxZ - 0.35),
  );
  scene.add(group);

  const material = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.72, depthWrite: false, side: THREE.DoubleSide });
  if (kind === "prototype") group.add(new THREE.Mesh(new THREE.BoxGeometry(0.22, 0.22, 0.22), material));
  else if (kind === "marker") group.add(new THREE.Mesh(new THREE.OctahedronGeometry(0.14, 0), material));
  else if (kind === "question") {
    groupBox(group, [0.38, 0.018, 0.26], [0, 0.18, 0], material);
    group.add(new THREE.Mesh(new THREE.TorusGeometry(0.09, 0.008, 8, 24), material));
  } else {
    groupBox(group, [kind === "note" ? 0.34 : 0.16, 0.018, kind === "note" ? 0.24 : 0.16], [0, 0.16, 0], material);
  }

  const light = new THREE.PointLight(color, 0.42, 1.7, 2);
  light.position.set(group.position.x, 0.38, group.position.z);
  scene.add(light);
  const object: AlpeccaIdeaObject = { id, roomId: room.id, label, kind, group, material, light, life: 42, pulseTimer: 4.5 };
  alpeccaIdeaObjects.push(object);
  register({
    id,
    label: `Inspect ${kind}: ${label.slice(0, 34)}`,
    root: group,
    range: 1.7,
    type: "momentary",
    onUse: () => {
      object.pulseTimer = Math.max(object.pulseTimer, 3);
      return `Alpecca ${kind}: ${label}`;
    },
  });
  rememberAlpeccaJournalEntry(`Created ${kind} in ${room.name}: ${label}`);
  appendAlpeccaLog("System", `Created ${kind} in ${room.name}`);
  setAlpeccaActivity(`Alpecca created a ${kind} in ${room.name}.`, "create");
  alpecca.glitchTimer = Math.max(alpecca.glitchTimer, 0.34);
  alpeccaProfileGlitchTimer = Math.max(alpeccaProfileGlitchTimer, 0.55);
  return object;
}

function updateAlpeccaIdeaObjects(dt: number) {
  const now = performance.now();
  for (let i = alpeccaIdeaObjects.length - 1; i >= 0; i -= 1) {
    const object = alpeccaIdeaObjects[i];
    object.life -= dt;
    if (object.pulseTimer > 0) object.pulseTimer -= dt;
    const active = object.pulseTimer > 0;
    const pulse = active ? 0.6 + Math.sin(now / 90 + i) * 0.22 : 0.2 + Math.sin(now / 700 + i) * 0.04;
    object.material.opacity = THREE.MathUtils.damp(object.material.opacity, THREE.MathUtils.clamp(pulse * calmVisualMultiplier(active), 0.08, 0.8), 8, dt);
    object.light.intensity = THREE.MathUtils.damp(object.light.intensity, (active ? 0.42 : 0.08) * calmLightMultiplier(active), 7, dt);
    object.group.rotation.y += dt * (active ? 0.9 : 0.18);
    if (object.life <= 0) {
      alpeccaIdeaObjects.splice(i, 1);
      disposeAlpeccaIdeaObject(object);
    }
  }
}

function updateAlpeccaPerception(dt: number) {
  if (alpeccaPerceptionSendTimer > 0) alpeccaPerceptionSendTimer = Math.max(0, alpeccaPerceptionSendTimer - dt);
  if (!alpecca.ready || alpeccaChat.matches(":focus-within")) return;
  alpeccaPerceptionTimer -= dt;
  if (alpeccaPerceptionTimer > 0) return;
  alpeccaPerceptionTimer = alpecca.inspectTimer > 0 ? 2.2 : 5.6;
  const target = visibleAlpeccaTargets()[0];
  const room = officeRoomAtPosition(alpecca.group.position.x, alpecca.group.position.z);
  if (target) recordAlpeccaPerception(target.label, target.roomId, target.source);
  else recordAlpeccaPerception(room.system, room.id, "room scan");
}

function featureColorForRoom(roomId: string) {
  const point = alpeccaExplorePoints.find((item) => item.roomId === roomId);
  return point?.featureId ? alpeccaSourceFeatures[point.featureId]?.color ?? "#8eeeff" : "#8eeeff";
}

function addAlpeccaMemoryTrace(roomId: string, roomName: string, pos: THREE.Vector3Tuple, yaw: number) {
  const color = featureColorForRoom(roomId);
  const group = new THREE.Group();
  group.name = `${roomName} Alpecca memory trace`;
  group.position.set(...pos);
  group.rotation.y = yaw;
  scene.add(group);

  groupBox(group, [0.58, 0.045, 0.34], [0, 0.04, 0], materials.metal);
  groupBox(group, [0.42, 0.018, 0.24], [0, 0.085, 0.015], materials.paper);

  const material = new THREE.MeshBasicMaterial({
    color,
    transparent: true,
    opacity: 0.22,
    depthWrite: false,
    side: THREE.DoubleSide,
  });
  const ring = new THREE.Mesh(new THREE.RingGeometry(0.16, 0.23, 32), material);
  ring.name = `${roomName} memory trace pulse ring`;
  ring.rotation.x = -Math.PI / 2;
  ring.position.set(0, 0.12, 0);
  ring.renderOrder = 7;
  group.add(ring);

  const core = new THREE.Mesh(new THREE.OctahedronGeometry(0.065, 0), material);
  core.name = `${roomName} memory trace core`;
  core.position.set(0, 0.29, 0);
  core.renderOrder = 8;
  group.add(core);

  const light = new THREE.PointLight(color, 0.06, 1.7, 2);
  light.position.set(pos[0], pos[1] + 0.36, pos[2]);
  scene.add(light);

  const trace: AlpeccaMemoryTrace = {
    roomId,
    roomName,
    group,
    material,
    light,
    note: `${roomName}: waiting for Alpecca's first inspection.`,
    visits: 0,
    pulseTimer: 0,
  };
  alpeccaMemoryTraces.set(roomId, trace);

  register({
    id: `alpecca-memory-${roomId}`,
    label: `Read ${roomName} memory trace`,
    root: group,
    range: 1.85,
    type: "momentary",
    onUse: () => {
      trace.pulseTimer = Math.max(trace.pulseTimer, 2.2);
      pulseAlpeccaRoomDevice(roomId, 1.4);
      return trace.note;
    },
  });
  addContactOcclusion(`${roomName} memory trace contact ao`, [0.74, 0.48], [pos[0], 0.012, pos[2]], 0.12);
}

function updateAlpeccaMemoryTrace(point: AlpeccaExplorePoint, online: boolean) {
  const trace = alpeccaMemoryTraces.get(point.roomId);
  if (!trace) return;
  trace.visits += 1;
  trace.pulseTimer = Math.max(trace.pulseTimer, 4.2);
  const feature = point.featureId ? alpeccaSourceFeatures[point.featureId] : null;
  const source = feature ? `${feature.room} source` : "navigation source";
  trace.note = `${point.roomName} memory ${trace.visits}: Alpecca ${point.action}. ${online ? "System online" : "System offline"}. Linked to ${source}.`;
  recordAlpeccaEnvironmentObservation(point, online);
}

function updateAlpeccaMemoryTraces(dt: number) {
  const now = performance.now();
  for (const trace of alpeccaMemoryTraces.values()) {
    if (trace.pulseTimer > 0) trace.pulseTimer -= dt;
    const nearAlpecca = Math.hypot(trace.group.position.x - alpecca.group.position.x, trace.group.position.z - alpecca.group.position.z) < 1.2;
    if (nearAlpecca && alpecca.inspectTimer > 0.35) trace.pulseTimer = Math.max(trace.pulseTimer, 0.8);
    const active = trace.pulseTimer > 0 || nearAlpecca;
    const opacity = active ? 0.52 + Math.sin(now / 115 + trace.group.position.x) * 0.17 : 0.18;
    trace.material.opacity = THREE.MathUtils.damp(trace.material.opacity, opacity * calmVisualMultiplier(active), 8, dt);
    trace.light.intensity = THREE.MathUtils.damp(trace.light.intensity, (active ? 0.32 : 0.045) * calmLightMultiplier(active), 7, dt);
    trace.group.scale.setScalar(THREE.MathUtils.damp(trace.group.scale.x, active ? 1.04 : 0.96, 8, dt));
  }
}

function addAlpeccaPlantCareSystem(id: string, label: string, group: THREE.Group, pos: THREE.Vector3Tuple, height: number, color = "#8eeeff") {
  const material = new THREE.MeshBasicMaterial({
    color,
    transparent: true,
    opacity: 0,
    depthWrite: false,
    side: THREE.DoubleSide,
  });
  const ring = new THREE.Mesh(new THREE.RingGeometry(0.18, 0.25, 28), material);
  ring.name = `${label} Alpecca care ring`;
  ring.rotation.x = -Math.PI / 2;
  ring.position.set(0, height, 0);
  ring.renderOrder = 7;
  group.add(ring);

  const light = new THREE.PointLight(color, 0, 1.55, 2);
  light.position.set(pos[0], pos[1] + height + 0.08, pos[2]);
  scene.add(light);

  alpeccaHomeSystems.push({
    id,
    kind: "plant",
    roomId: officeRoomAtPosition(pos[0], pos[2]).id,
    label,
    root: group,
    signalMaterial: material,
    signalLight: light,
    pulseTimer: 0,
    cooldown: 2,
  });
}

function updateAlpeccaHomeSystems(dt: number) {
  if (alpeccaHomeNoticeTimer > 0) alpeccaHomeNoticeTimer -= dt;
  if (!alpecca.ready) return;

  const playerEngaged = alpecca.attentionTimer > 0 || alpeccaAiAwaitingReply || alpeccaLiveAttentionTimer > 0 || !alpeccaChat.classList.contains("hidden");
  const now = performance.now();
  for (const system of alpeccaHomeSystems) {
    if (system.cooldown > 0) system.cooldown -= dt;
    if (system.pulseTimer > 0) system.pulseTimer -= dt;

    const world = system.root.getWorldPosition(targetWorldPosition);
    const distanceToAlpecca = Math.hypot(world.x - alpecca.group.position.x, world.z - alpecca.group.position.z);
    const nearAlpecca = distanceToAlpecca < (system.kind === "lamp" ? 1.55 : 1.12);

    if (system.kind === "lamp" && system.item && nearAlpecca && system.item.active === false && system.cooldown <= 0 && alpeccaHomeNoticeTimer <= 0 && !playerEngaged) {
      system.item.onUse(system.item);
      system.cooldown = 28;
      system.pulseTimer = 2.2;
      alpeccaHomeNoticeTimer = 4.5;
      pulseAlpeccaRoomDevice(system.roomId, 1.6);
      showMessage(`Alpecca switches on ${system.label}.`, 2.7);
    }

    if (system.kind === "plant" && nearAlpecca && system.cooldown <= 0 && alpeccaHomeNoticeTimer <= 0 && !playerEngaged) {
      system.cooldown = 18;
      system.pulseTimer = 2.4;
      alpeccaHomeNoticeTimer = 4;
      pulseAlpeccaRoomDevice(system.roomId, 1.3);
      showMessage(`Alpecca tends ${system.label.toLowerCase()}.`, 2.5);
    }

    if (system.signalMaterial) {
      const active = system.pulseTimer > 0;
      const opacity = active ? 0.46 + Math.sin(now / 120 + world.x) * 0.16 : 0;
      system.signalMaterial.opacity = THREE.MathUtils.damp(system.signalMaterial.opacity, opacity * calmVisualMultiplier(active), 8, dt);
    }
    if (system.signalLight) {
      const active = system.pulseTimer > 0;
      system.signalLight.intensity = THREE.MathUtils.damp(system.signalLight.intensity, (active ? 0.34 : 0) * calmLightMultiplier(active), 7, dt);
    }
  }
}

function addDocumentStack(group: THREE.Group, x: number, y: number, z: number, count = 4) {
  for (let i = 0; i < count; i += 1) {
    const page = groupBox(group, [0.42, 0.012, 0.28], [x + i * 0.012, y + i * 0.014, z - i * 0.01], materials.paper);
    page.rotation.y = (i - 1.5) * 0.06;
  }
}

function addCableSegments(group: THREE.Group, colorMaterial: THREE.Material) {
  groupBox(group, [0.95, 0.035, 0.045], [0, 0.035, 0], colorMaterial);
  groupBox(group, [0.045, 0.035, 0.55], [0.44, 0.035, 0.25], colorMaterial);
  groupBox(group, [0.62, 0.03, 0.035], [-0.3, 0.034, -0.22], colorMaterial);
}

function addOfficeDetailClusters() {
  addAlpeccaDetailPoint(
    "hq-routing-cables",
    "hq-control",
    "HQ routing cable loom",
    "The cable loom labels the live bridge, room routes, and Alpecca source feed.",
    [-3.62, 0, 2.78],
    alpeccaSourceFeatures.home.color,
    (group, signal) => {
      addCableSegments(group, materials.metal);
      groupBox(group, [0.36, 0.045, 0.18], [0.55, 0.075, 0.52], materials.screen);
      groupBox(group, [0.18, 0.02, 0.07], [0.55, 0.115, 0.52], signal);
      addContactOcclusion("hq routing cable ao", [1.25, 0.9], [-3.62, 0.012, 2.78], 0.12);
    },
  );

  addAlpeccaDetailPoint(
    "library-index-cards",
    "library",
    "Library index card tray",
    "A tray of memory cards marks references Alpecca has already cross-checked.",
    [-6.52, 0.94, -1.02],
    alpeccaSourceFeatures.memory.color,
    (group, signal) => {
      groupBox(group, [0.62, 0.08, 0.32], [0, 0.04, 0], materials.darkWood);
      for (let i = 0; i < 6; i += 1) groupBox(group, [0.055, 0.22, 0.24], [-0.23 + i * 0.09, 0.18, 0.02], i % 2 ? materials.paper : signal);
      addDocumentStack(group, 0.38, 0.11, -0.04, 3);
    },
  );

  addAlpeccaDetailPoint(
    "observatory-signal-reels",
    "observatory",
    "Observatory signal reels",
    "Media reels spool creative review signals before they enter the source bridge.",
    [5.75, 0.98, 4.86],
    alpeccaSourceFeatures.soul.color,
    (group, signal) => {
      const left = groupCylinder(group, 0.16, 0.055, [-0.2, 0.09, 0], materials.metal, 24);
      const right = groupCylinder(group, 0.16, 0.055, [0.2, 0.09, 0], materials.metal, 24);
      left.rotation.x = Math.PI / 2;
      right.rotation.x = Math.PI / 2;
      groupBox(group, [0.54, 0.04, 0.08], [0, 0.09, 0], signal);
      groupBox(group, [0.72, 0.05, 0.34], [0, 0.02, 0], materials.board);
    },
  );

  addAlpeccaDetailPoint(
    "workshop-tool-roll",
    "workshop",
    "Workshop calibrated tool roll",
    "Small prototype tools are sorted by build risk so Alpecca can choose a safe test.",
    [5.18, 0.98, -4.36],
    alpeccaSourceFeatures.studio.color,
    (group, signal) => {
      groupBox(group, [0.82, 0.035, 0.34], [0, 0.02, 0], materials.fabric);
      for (let i = 0; i < 5; i += 1) {
        const tool = groupBox(group, [0.045, 0.045, 0.28], [-0.3 + i * 0.15, 0.08, 0.01], i === 2 ? signal : materials.metal);
        tool.rotation.y = (i - 2) * 0.12;
      }
      groupCylinder(group, 0.055, 0.22, [0.43, 0.09, -0.03], materials.lightWood, 14).rotation.z = Math.PI / 2;
    },
  );

  addAlpeccaDetailPoint(
    "self-design-swatch-board",
    "self-design",
    "Self Design swatch board",
    "Avatar color swatches are pinned here for mood, identity, and wardrobe alignment.",
    [-6.55, 1.34, 1.18],
    alpeccaSourceFeatures.self.color,
    (group, signal) => {
      groupBox(group, [0.82, 0.5, 0.05], [0, 0, -0.03], materials.board);
      const swatches: Array<[number, number, THREE.Material]> = [
        [-0.24, 0.12, materials.flower],
        [0, 0.12, signal],
        [0.24, 0.12, materials.glass],
        [-0.12, -0.13, materials.paper],
        [0.14, -0.13, materials.fabric],
      ];
      for (const [x, y, mat] of swatches) groupBox(group, [0.16, 0.13, 0.035], [x, y, 0.02], mat);
    },
  );
}

function addRoomLabel(label: string, pos: THREE.Vector3Tuple, yaw: number) {
  const group = new THREE.Group();
  group.position.set(...pos);
  group.rotation.y = yaw;
  scene.add(group);
  groupBox(group, [1.7, 0.42, 0.06], [0, 0, 0], materials.board);
  groupBox(group, [1.45, 0.08, 0.07], [0, 0.08, 0.03], materials.screen);
  groupBox(group, [1.1, 0.05, 0.075], [0, -0.08, 0.03], materials.paper);
  group.name = label;
}

function addMonitorWall(pos: THREE.Vector3Tuple, yaw: number, count: number) {
  const group = new THREE.Group();
  group.position.set(...pos);
  group.rotation.y = yaw;
  scene.add(group);
  groupBox(group, [count * 0.78 + 0.25, 1.0, 0.08], [0, 0, 0], materials.board);
  for (let i = 0; i < count; i += 1) {
    groupBox(group, [0.62, 0.42, 0.05], [(i - (count - 1) / 2) * 0.75, 0.12, 0.05], materials.screen);
    groupBox(group, [0.48, 0.04, 0.055], [(i - (count - 1) / 2) * 0.75, -0.18, 0.06], materials.paper);
  }
}

function addWhiteboard(pos: THREE.Vector3Tuple, yaw: number, name: string) {
  const group = new THREE.Group();
  group.name = name;
  group.position.set(...pos);
  group.rotation.y = yaw;
  scene.add(group);
  groupBox(group, [1.65, 0.9, 0.06], [0, 0, 0], materials.paper);
  for (let i = 0; i < 4; i += 1) groupBox(group, [0.18, 0.06, 0.07], [-0.55 + i * 0.35, 0.2 - i * 0.12, 0.04], materials.screen);
}

function addBookshelf(pos: THREE.Vector3Tuple, yaw: number) {
  const group = new THREE.Group();
  group.position.set(...pos);
  group.rotation.y = yaw;
  scene.add(group);
  groupBox(group, [1.55, 2.0, 0.38], [0, 1.0, 0], materials.darkWood);
  for (let shelf = 0; shelf < 4; shelf += 1) {
    groupBox(group, [1.42, 0.07, 0.42], [0, 0.25 + shelf * 0.45, 0.03], materials.lightWood);
    for (let b = 0; b < 5; b += 1) {
      const mat = b % 2 === 0 ? materials.screen : materials.paper;
      groupBox(group, [0.13, 0.32, 0.12], [-0.55 + b * 0.24, 0.43 + shelf * 0.45, 0.14], mat);
    }
  }
}

function addWorkbench(pos: THREE.Vector3Tuple, yaw: number) {
  const group = new THREE.Group();
  group.position.set(...pos);
  group.rotation.y = yaw;
  scene.add(group);
  groupBox(group, [2.4, 0.16, 0.78], [0, 0.9, 0], materials.darkWood);
  groupBox(group, [2.1, 0.9, 0.08], [0, 1.45, -0.38], materials.board);
  for (let i = 0; i < 5; i += 1) groupBox(group, [0.09, 0.35, 0.08], [-0.85 + i * 0.42, 1.48, -0.31], materials.metal);
  groupBox(group, [0.48, 0.3, 0.42], [0.55, 1.13, 0.05], materials.metal);
  groupBox(group, [0.35, 0.22, 0.35], [-0.45, 1.1, 0.05], materials.screen);
}

function chooseAlpeccaSelfReviewTarget() {
  if (alpecca.stuckTimer > 0.35 || alpecca.avoidTimer > 0.2) return "workshop";
  if (alpeccaAppMemory.pendingReturn || alpeccaAppMemory.recursiveDepth % 4 === 1) return "self-design";
  const offline = officeRooms.find((room) => !activeRoomIds.has(room.stationId));
  if (offline && alpeccaAppMemory.recursiveDepth % 2 === 0) return offline.id;
  if (alpeccaAiMood.includes("fear") || alpeccaAiMood.includes("worried") || alpeccaAiMood.includes("anxious")) return "hq-control";
  if ((Number.isFinite(alpeccaAiState.energy) ? alpeccaAiState.energy : 0.5) < 0.28) return "library";
  return currentOfficeRoom().id === "entry" ? "self-design" : currentOfficeRoom().id;
}

function selfReviewActionForRoom(roomId: string) {
  if (roomId === "hq-control") return "stabilize the plan before moving again";
  if (roomId === "library") return "compare memory against what just happened";
  if (roomId === "observatory") return "watch the work from a new angle";
  if (roomId === "workshop") return "test a cleaner path and avoid collisions";
  if (roomId === "self-design") return "check identity, pose, and intent in the mirror";
  return "pause, listen, and choose the next room deliberately";
}

const alpeccaIdentityQuestions = [
  "What can I verify from memory and action?",
  "What values should constrain my next choice?",
  "How did experience change my behavior?",
  "What remains uncertain about my self-model?",
];

function currentAlpeccaIdentityQuestion() {
  return alpeccaIdentityQuestions[alpeccaAppMemory.identityReflections % alpeccaIdentityQuestions.length];
}

function pulseAlpeccaIdentityConsole(seconds = 3.4) {
  if (!alpeccaIdentityConsole) return;
  alpeccaIdentityConsole.pulseTimer = Math.max(alpeccaIdentityConsole.pulseTimer, seconds);
}

function runAlpeccaIdentityReflection(reason: string, announce = true) {
  const question = currentAlpeccaIdentityQuestion();
  alpeccaAppMemory.identityReflections += 1;
  alpeccaAppMemory.recursiveDepth += 1;
  alpeccaAppMemory.activeIdentityQuestion = question;
  const note = `Identity reflection ${alpeccaAppMemory.identityReflections}: ${question} Evidence: ${reason}. Boundary: identity is modeled from memory and action, not proof of consciousness.`;
  alpeccaAppMemory.lastIdentityReflection = note;
  alpeccaAppMemory.identityNotes = [...alpeccaAppMemory.identityNotes, note].slice(-8);
  alpeccaAppMemory.note = note;
  saveAlpeccaAppMemory();
  rememberAlpeccaJournalEntry(note);
  writeAlpeccaSelfTrace(note);
  pulseAlpeccaIdentityConsole(4.4);
  pulseAlpeccaAgiJournal(3.2);
  pulseAlpeccaSourceTerminal("self", 3.2, true);
  pulseAlpeccaSourceDashboard("self", 3);
  pulseAlpeccaRoomDevice("self-design", 2.8);
  pulseAlpeccaRoomDetails("self-design", 2.4);
  routeAlpeccaToRoom("self-design");
  const philosophical = alpeccaAgiLayers.find((layer) => layer.id === "philosophical");
  if (philosophical) philosophical.pulseTimer = Math.max(philosophical.pulseTimer, 5);
  alpecca.glitchTimer = Math.max(alpecca.glitchTimer, 0.2);
  focusAlpecca(1.7, "idleDown");
  if (announce) showMessage("Alpecca saved an identity reflection.", 3.4);
  sendAlpeccaRecursiveMemory(`${note} Answer with one careful self-model adjustment under 18 words.`, false);
  return note;
}

function addAlpeccaIdentityConsole(pos: THREE.Vector3Tuple, yaw: number) {
  const group = new THREE.Group();
  group.name = "Alpecca identity reflection console";
  group.position.set(...pos);
  group.rotation.y = yaw;
  group.scale.setScalar(0.9);
  scene.add(group);

  groupBox(group, [1.08, 0.1, 0.62], [0, 0.5, 0], materials.darkWood);
  groupBox(group, [0.1, 0.5, 0.08], [-0.42, 0.25, -0.22], materials.darkWood);
  groupBox(group, [0.1, 0.5, 0.08], [0.42, 0.25, -0.22], materials.darkWood);
  groupBox(group, [0.1, 0.5, 0.08], [-0.42, 0.25, 0.22], materials.darkWood);
  groupBox(group, [0.1, 0.5, 0.08], [0.42, 0.25, 0.22], materials.darkWood);
  groupBox(group, [0.86, 0.62, 0.08], [0, 0.88, -0.22], materials.board);
  groupBox(group, [0.94, 0.05, 0.1], [0, 1.22, -0.18], materials.metal);
  groupBox(group, [0.94, 0.05, 0.1], [0, 0.52, -0.18], materials.metal);
  addContactOcclusion("Alpecca identity console contact ao", [1.18, 0.82], [pos[0], 0.012, pos[2]], 0.13);
  addGroundCable("Alpecca identity console cable", [pos[0], 0.04, pos[2]], [-5.75, 0.04, 1.35], alpeccaSourceFeatures.self.color);

  const coreMaterial = new THREE.MeshBasicMaterial({
    color: alpeccaSourceFeatures.self.color,
    transparent: true,
    opacity: 0.44,
    depthWrite: false,
  });
  const core = new THREE.Mesh(new THREE.OctahedronGeometry(0.1, 0), coreMaterial);
  core.name = "Alpecca identity reflection core";
  core.position.set(0, 1.02, -0.12);
  core.renderOrder = 9;
  group.add(core);

  const slotMaterials: THREE.MeshBasicMaterial[] = [];
  const colors = [alpeccaSourceFeatures.self.color, alpeccaSourceFeatures.memory.color, alpeccaSourceFeatures.studio.color, alpeccaSourceFeatures.soul.color];
  for (let i = 0; i < alpeccaIdentityQuestions.length; i += 1) {
    const material = new THREE.MeshBasicMaterial({
      color: colors[i],
      transparent: true,
      opacity: 0.22,
      depthWrite: false,
    });
    slotMaterials.push(material);
    const y = 1.1 - i * 0.15;
    const node = new THREE.Mesh(new THREE.BoxGeometry(0.13, 0.09, 0.026), material);
    node.name = `Alpecca identity question node ${i + 1}`;
    node.position.set(-0.32, y, -0.13);
    node.renderOrder = 8;
    group.add(node);
    const rail = new THREE.Mesh(new THREE.BoxGeometry(0.44, 0.022, 0.02), material);
    rail.name = `Alpecca identity question rail ${i + 1}`;
    rail.position.set(0.02, y, -0.13);
    rail.renderOrder = 8;
    group.add(rail);
  }

  const light = new THREE.PointLight(alpeccaSourceFeatures.self.color, 0.14, 2.3, 2);
  light.position.set(0, 1.1, 0.08);
  group.add(light);

  alpeccaIdentityConsole = { group, core, coreMaterial, slotMaterials, light, pulseTimer: 0, readIndex: 0 };

  register({
    id: "alpecca-identity-console",
    label: "Reflect with Alpecca identity console",
    root: group,
    range: 2.1,
    type: "momentary",
    onUse: () => {
      return runAlpeccaIdentityReflection("player asked the identity console for a careful self-model check");
    },
  });
}

function updateAlpeccaIdentityConsole(dt: number) {
  if (!alpeccaIdentityConsole) return;
  const console = alpeccaIdentityConsole;
  const now = performance.now();
  if (console.pulseTimer > 0) console.pulseTimer -= dt;
  const active = console.pulseTimer > 0;
  const selectedIndex = alpeccaAppMemory.identityReflections % alpeccaIdentityQuestions.length;
  console.core.rotation.x += dt * (active ? 1.45 : 0.25);
  console.core.rotation.y += dt * (active ? 2.35 : 0.42);
  console.coreMaterial.opacity = THREE.MathUtils.damp(console.coreMaterial.opacity, (active ? 0.58 + Math.sin(now / 100) * 0.18 : 0.24) * calmVisualMultiplier(active), 8, dt);
  console.light.intensity = THREE.MathUtils.damp(console.light.intensity, (active ? 0.46 : 0.09) * calmLightMultiplier(active), 7, dt);
  for (const [index, material] of console.slotMaterials.entries()) {
    const selected = index === selectedIndex;
    const opacity = selected ? 0.52 + Math.sin(now / 130 + index) * 0.16 : 0.16 + Math.min(0.3, alpeccaAppMemory.identityReflections * 0.035);
    material.opacity = THREE.MathUtils.damp(material.opacity, THREE.MathUtils.clamp(opacity * calmVisualMultiplier(selected || active), 0.1, 0.78), 8, dt);
  }
}

function runAlpeccaSelfReview(reason: string) {
  if (!alpeccaSelfMirror) return;
  const targetRoomId = chooseAlpeccaSelfReviewTarget();
  const targetRoom = officeRooms.find((room) => room.id === targetRoomId) ?? entryRoom;
  alpecca.selfReviewTargetRoom = targetRoom.id;
  alpeccaAppMemory.recursiveDepth += 1;
  alpeccaSelfMirror.recursiveDepth += 1;
  alpeccaSelfMirror.reviewTimer = Math.max(alpeccaSelfMirror.reviewTimer, 3.8);
  alpeccaSelfMirror.pulseTimer = Math.max(alpeccaSelfMirror.pulseTimer, 4.4);
  alpeccaSelfMirror.cooldown = 18;
  alpecca.glitchTimer = Math.max(alpecca.glitchTimer, 0.28);
  alpeccaSelfMirror.note = `Self-review ${alpeccaSelfMirror.recursiveDepth}: ${reason}. I should ${selfReviewActionForRoom(targetRoom.id)}.`;
  alpeccaAppMemory.note = alpeccaSelfMirror.note;
  saveAlpeccaAppMemory();
  rememberAlpeccaJournalEntry(alpeccaSelfMirror.note);
  writeAlpeccaSelfTrace(alpeccaSelfMirror.note);
  if (targetRoom.id === "self-design" || alpeccaSelfMirror.recursiveDepth % 2 === 0) {
    runAlpeccaIdentityReflection(`mirror self-review ${alpeccaSelfMirror.recursiveDepth}: ${reason}`, false);
  }
  routeAlpeccaToRoom(targetRoom.id);
  showMessage(`Alpecca self-review: ${selfReviewActionForRoom(targetRoom.id)}.`, 3.8);
  sendAlpeccaRecursiveMemory(alpeccaSelfMirror.note, true);
}

function syncAlpeccaSelfMirrorReflection(dt: number) {
  if (!alpeccaSelfMirror || !alpecca.sprite) return;
  const animation = alpecca.animations.get(alpecca.state);
  if (animation && alpeccaSelfMirror.reflection.material.map !== animation.texture) {
    alpeccaSelfMirror.reflection.material.map = animation.texture;
    alpeccaSelfMirror.reflection.material.needsUpdate = true;
  }

  alpeccaMirrorLocal.copy(alpecca.group.position);
  alpeccaSelfMirror.group.worldToLocal(alpeccaMirrorLocal);
  const inFront = alpeccaMirrorLocal.z > 0.15;
  const depthFocus = THREE.MathUtils.clamp(1 - Math.abs(alpeccaMirrorLocal.z - 1.45) / 2.25, 0, 1);
  const horizontalFocus = THREE.MathUtils.clamp(1 - Math.abs(alpeccaMirrorLocal.x) / 1.85, 0, 1);
  const mirrorFocus = inFront ? depthFocus * horizontalFocus : 0;
  alpecca.mirrorReflection = THREE.MathUtils.damp(alpecca.mirrorReflection, mirrorFocus, 8, dt);

  const perspectiveScale = THREE.MathUtils.clamp(1.34 - alpeccaMirrorLocal.z * 0.12, 0.92, 1.28);
  const mirrorScale = THREE.MathUtils.clamp(alpecca.displayScale * perspectiveScale, 0.92, 1.48);
  alpeccaSelfMirror.reflection.scale.set(alpecca.flipX ? mirrorScale : -mirrorScale, mirrorScale, 1);
  alpeccaSelfMirror.reflection.position.x = THREE.MathUtils.damp(
    alpeccaSelfMirror.reflection.position.x,
    THREE.MathUtils.clamp(-alpeccaMirrorLocal.x * 0.34, -0.34, 0.34),
    8,
    dt,
  );
  alpeccaSelfMirror.reflection.position.y = THREE.MathUtils.damp(
    alpeccaSelfMirror.reflection.position.y,
    0.12 + (alpecca.displaySpriteY - 0.92) * 0.22,
    10,
    dt,
  );
  alpeccaSelfMirror.reflection.rotation.z = THREE.MathUtils.damp(alpeccaSelfMirror.reflection.rotation.z, -alpecca.bodyLean * 0.55, 10, dt);
}

function addDesignMirror(pos: THREE.Vector3Tuple, yaw: number) {
  const group = new THREE.Group();
  group.name = "Alpecca recursive self mirror";
  group.position.set(...pos);
  group.rotation.y = yaw;
  scene.add(group);

  groupBox(group, [1.14, 1.98, 0.08], [0, 0.32, -0.05], materials.metal);
  groupBox(group, [0.92, 0.08, 0.12], [0, -0.74, 0.03], materials.screen);
  groupBox(group, [0.92, 0.08, 0.12], [0, 1.38, 0.03], materials.screen);
  groupBox(group, [1.02, 0.06, 0.16], [0, -pos[1] + 0.07, 0.04], materials.metal);
  groupBox(group, [0.08, 0.52, 0.08], [-0.38, -0.98, 0.035], materials.metal);
  groupBox(group, [0.08, 0.52, 0.08], [0.38, -0.98, 0.035], materials.metal);
  addPanelCableDrop(group, 0.43, -0.76, pos[1], 0.08, materials.metal);
  addContactOcclusion("Alpecca self mirror contact ao", [1.2, 0.5], [pos[0], 0.012, pos[2]], 0.13);

  const surfaceMaterial = new THREE.MeshBasicMaterial({
    color: "#bfeaf2",
    transparent: true,
    opacity: 0.34,
    depthWrite: false,
    side: THREE.DoubleSide,
  });
  const surface = new THREE.Mesh(new THREE.PlaneGeometry(0.92, 1.72), surfaceMaterial);
  surface.name = "Alpecca mirror reflective surface";
  surface.position.set(0, 0.32, 0.006);
  surface.renderOrder = 6;
  group.add(surface);

  const reflectionMaterial = new THREE.MeshBasicMaterial({
    color: "#ffffff",
    transparent: true,
    opacity: 0.72,
    alphaTest: 0.08,
    depthWrite: false,
    side: THREE.DoubleSide,
  });
  const reflection = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), reflectionMaterial);
  reflection.name = "Alpecca live mirror reflection";
  reflection.position.set(0, 0.12, 0.018);
  reflection.renderOrder = 8;
  group.add(reflection);

  const signalMaterial = new THREE.MeshBasicMaterial({
    color: alpeccaSourceFeatures.self.color,
    transparent: true,
    opacity: 0.2,
    depthWrite: false,
    side: THREE.DoubleSide,
  });
  const scanRing = new THREE.Mesh(new THREE.RingGeometry(0.5, 0.56, 48), signalMaterial);
  scanRing.name = "Alpecca self-review mirror ring";
  scanRing.position.set(0, 0.32, 0.026);
  scanRing.renderOrder = 9;
  group.add(scanRing);

  const critiqueBars: THREE.Mesh<THREE.BoxGeometry, THREE.MeshBasicMaterial>[] = [];
  for (let i = 0; i < 4; i += 1) {
    const bar = new THREE.Mesh(new THREE.BoxGeometry(0.055, 0.22 + i * 0.045, 0.035), signalMaterial);
    bar.name = `Alpecca self critique bar ${i + 1}`;
    bar.position.set(-0.44 + i * 0.12, -0.52, 0.04);
    bar.renderOrder = 10;
    group.add(bar);
    critiqueBars.push(bar);
  }

  const light = new THREE.PointLight(alpeccaSourceFeatures.self.color, 0.16, 2.8, 2);
  light.position.set(pos[0], pos[1] + 0.35, pos[2]);
  scene.add(light);

  alpeccaSelfMirror = {
    group,
    surfaceMaterial,
    reflection,
    signalMaterial,
    critiqueBars,
    light,
    pulseTimer: 0,
    reviewTimer: 0,
    cooldown: 6,
    recursiveDepth: alpeccaAppMemory.recursiveDepth,
    note: alpeccaAppMemory.note,
  };

  register({
    id: "alpecca-recursive-self-mirror",
    label: "Read Alpecca self mirror",
    root: group,
    range: 2.15,
    type: "momentary",
    onUse: () => {
      runAlpeccaSelfReview("player asked the mirror for a self-check");
      return alpeccaSelfMirror?.note ?? "The mirror is still gathering Alpecca's reflection.";
    },
  });
}

function updateAlpeccaSelfMirror(dt: number) {
  if (!alpeccaSelfMirror) return;
  if (alpeccaSelfMirror.pulseTimer > 0) alpeccaSelfMirror.pulseTimer -= dt;
  if (alpeccaSelfMirror.reviewTimer > 0) alpeccaSelfMirror.reviewTimer -= dt;
  if (alpeccaSelfMirror.cooldown > 0) alpeccaSelfMirror.cooldown -= dt;
  syncAlpeccaSelfMirrorReflection(dt);

  const now = performance.now();
  const nearAlpecca = Math.hypot(alpeccaSelfMirror.group.position.x - alpecca.group.position.x, alpeccaSelfMirror.group.position.z - alpecca.group.position.z) < 1.45;
  if (nearAlpecca && alpecca.inspectTimer > 0.65 && alpeccaSelfMirror.cooldown <= 0) {
    runAlpeccaSelfReview("I looked at my reflected movement and checked what needs improving");
  }

  const active = alpeccaSelfMirror.pulseTimer > 0 || alpeccaSelfMirror.reviewTimer > 0 || nearAlpecca;
  const glow = active ? 0.44 + Math.sin(now / 120) * 0.18 : 0.22 + Math.sin(now / 900) * 0.04;
  const surfaceOpacity = active ? 0.42 : alpeccaAppMemory.visualCalmMode ? 0.22 : 0.28;
  alpeccaSelfMirror.surfaceMaterial.opacity = THREE.MathUtils.damp(alpeccaSelfMirror.surfaceMaterial.opacity, surfaceOpacity, 7, dt);
  const reflectionOpacity = 0.12 + alpecca.mirrorReflection * (active ? 0.72 : 0.46);
  alpeccaSelfMirror.reflection.material.opacity = THREE.MathUtils.damp(alpeccaSelfMirror.reflection.material.opacity, reflectionOpacity, 8, dt);
  alpeccaSelfMirror.signalMaterial.opacity = THREE.MathUtils.damp(alpeccaSelfMirror.signalMaterial.opacity, glow * calmVisualMultiplier(active), 8, dt);
  alpeccaSelfMirror.light.intensity = THREE.MathUtils.damp(alpeccaSelfMirror.light.intensity, (active ? 0.52 : 0.12) * calmLightMultiplier(active), 7, dt);
  alpeccaSelfMirror.group.children.forEach((child) => {
    if (child.name === "Alpecca self-review mirror ring") child.rotation.z += dt * (active ? 1.6 : 0.22);
  });
  alpeccaSelfMirror.critiqueBars.forEach((bar, index) => {
    const targetY = 1 + (active ? Math.sin(now / (140 + index * 25) + index) * 0.24 : 0);
    bar.scale.y = THREE.MathUtils.damp(bar.scale.y, targetY, 8, dt);
  });
}

function addAlpeccaSystemsGateway(pos: THREE.Vector3Tuple, yaw: number) {
  const group = new THREE.Group();
  group.name = "Alpecca systems gateway";
  group.position.set(...pos);
  group.rotation.y = yaw;
  scene.add(group);

  groupBox(group, [0.92, 1.16, 0.08], [0, 0.18, -0.03], materials.board);
  groupBox(group, [0.74, 0.82, 0.045], [0, 0.22, 0.025], materials.screen);
  groupBox(group, [0.82, 0.06, 0.16], [0, -pos[1] + 0.06, 0.04], materials.metal);
  groupBox(group, [0.08, 0.46, 0.08], [-0.34, -0.56, 0.035], materials.metal);
  groupBox(group, [0.08, 0.46, 0.08], [0.34, -0.56, 0.035], materials.metal);
  addPanelCableDrop(group, -0.39, -0.42, pos[1], 0.07, materials.metal);
  addContactOcclusion("Alpecca systems gateway contact ao", [1.02, 0.52], [pos[0], 0.012, pos[2]], 0.14);
  const material = new THREE.MeshBasicMaterial({
    color: alpeccaSourceFeatures.home.color,
    transparent: true,
    opacity: 0.28,
    depthWrite: false,
    side: THREE.DoubleSide,
  });
  const ring = new THREE.Mesh(new THREE.RingGeometry(0.26, 0.34, 48), material);
  ring.name = "Alpecca systems gateway ring";
  ring.position.set(0, 0.25, 0.06);
  ring.renderOrder = 8;
  group.add(ring);
  const core = new THREE.Mesh(new THREE.OctahedronGeometry(0.095, 0), material);
  core.name = "Alpecca systems gateway core";
  core.position.set(0, 0.25, 0.08);
  core.renderOrder = 9;
  group.add(core);
  const light = new THREE.PointLight(alpeccaSourceFeatures.home.color, 0.12, 2.4, 2);
  light.position.set(pos[0], pos[1] + 0.35, pos[2]);
  scene.add(light);
  animatedProps.push((dt) => {
    const active = alpeccaAppMemory.pendingReturn || alpeccaAppMemory.recursiveDepth > 0;
    ring.rotation.z += dt * (active ? 1.1 : 0.35);
    core.rotation.y += dt * (active ? 1.8 : 0.5);
    material.opacity = THREE.MathUtils.damp(material.opacity, (active ? 0.5 : 0.24) * calmVisualMultiplier(active), 7, dt);
    light.intensity = THREE.MathUtils.damp(light.intensity, (active ? 0.44 : 0.12) * calmLightMultiplier(active), 7, dt);
  });

  register({
    id: "alpecca-systems-gateway",
    label: "Open Alpecca systems",
    root: group,
    range: 2.1,
    type: "momentary",
    onUse: () => {
      openAlpeccaSystems("overview", true);
      return alpeccaAppMemory.note;
    },
  });
}

function addActivationStation(id: string, label: string, pos: THREE.Vector3Tuple, message: string) {
  const group = new THREE.Group();
  const baseScale = 0.92;
  group.position.set(pos[0], 0, pos[2]);
  group.scale.setScalar(baseScale);
  scene.add(group);
  groupBox(group, [0.9, 0.05, 0.62], [0, 0.025, 0], materials.darkWood);
  for (const x of [-0.29, 0.29]) {
    groupBox(group, [0.075, Math.max(0.14, pos[1] - 0.12), 0.075], [x, Math.max(0.14, pos[1] - 0.12) / 2 + 0.05, -0.16], materials.metal);
  }
  groupBox(group, [0.82, 0.18, 0.55], [0, pos[1], 0], materials.screen);
  groupBox(group, [0.62, 0.1, 0.36], [0, pos[1] - 0.16, 0.02], materials.metal);
  addContactOcclusion(`${label} station contact ao`, [1.04, 0.76], [pos[0], 0.012, pos[2]], 0.15);
  const light = new THREE.PointLight("#4be4ff", 0.5, 2.5, 2);
  light.position.set(pos[0], pos[1] + 0.2, pos[2]);
  scene.add(light);
  register({
    id,
    label,
    root: group,
    range: 1.9,
    type: "collect",
    collected: false,
    onUse: (item) => {
      if (item.collected) return `${label.replace(/^(Activate|Sync|Start|Power|Calibrate) /, "")} already active.`;
      item.collected = true;
      activeRoomIds.add(id);
      activatedRooms += 1;
      updateEnvironmentModeUi();
      updateRoomPanel(true);
      light.intensity = 1.3;
      if (activatedRooms === activeRoomTotal()) {
        return isPrototypeMode()
          ? "All prototype stations are active. The void testing stage is fully online."
          : "All five rooms are active. The AI office HQ is fully online.";
      }
      return message;
    },
    update: (dt, item) => {
      const targetScale = baseScale * (item.collected ? 1.025 : 1);
      group.scale.setScalar(THREE.MathUtils.damp(group.scale.x, targetScale, 8, dt));
    },
  });
}

function addPlanter(pos: THREE.Vector3Tuple, flowering: boolean) {
  const group = new THREE.Group();
  group.position.set(...pos);
  scene.add(group);
  groupCylinder(group, 0.22, 0.34, [0, 0.17, 0], materials.darkWood, 16);
  for (let i = 0; i < 7; i += 1) {
    const leaf = groupBox(group, [0.08, 0.36, 0.04], [Math.sin(i) * 0.14, 0.48, Math.cos(i) * 0.14], materials.plant);
    leaf.rotation.z = (i - 3) * 0.22;
    leaf.rotation.y = i * 0.8;
  }
  if (flowering) addFlowerPot([pos[0], pos[1] + 0.42, pos[2]]);
  addAlpeccaPlantCareSystem(`planter-${pos[0]}-${pos[2]}`, flowering ? "flowering planter" : "planter", group, pos, 0.68, flowering ? "#d86a8d" : "#8eeeff");
}

function addFlowerPot(pos: THREE.Vector3Tuple) {
  const group = new THREE.Group();
  group.position.set(...pos);
  scene.add(group);
  groupCylinder(group, 0.11, 0.18, [0, 0.09, 0], materials.lightWood, 14);
  for (let i = 0; i < 4; i += 1) {
    groupBox(group, [0.035, 0.24, 0.025], [Math.sin(i * 1.7) * 0.06, 0.25, Math.cos(i * 1.7) * 0.06], materials.plant);
    const blossom = new THREE.Mesh(new THREE.SphereGeometry(0.055, 10, 8), materials.flower);
    blossom.position.set(Math.sin(i * 1.7) * 0.09, 0.38, Math.cos(i * 1.7) * 0.09);
    blossom.castShadow = true;
    group.add(blossom);
  }
  addAlpeccaPlantCareSystem(`flower-pot-${pos[0]}-${pos[2]}`, "flower pot", group, pos, 0.48, "#d86a8d");
}

function addPigeon(pos: THREE.Vector3Tuple, yaw: number) {
  const group = new THREE.Group();
  group.position.set(...pos);
  group.rotation.y = yaw;
  scene.add(group);
  const body = new THREE.Mesh(new THREE.SphereGeometry(0.17, 14, 10), materials.pigeon);
  body.scale.set(1.25, 0.75, 0.85);
  body.castShadow = true;
  group.add(body);
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.095, 12, 8), materials.pigeon);
  head.position.set(0.18, 0.1, 0);
  head.castShadow = true;
  group.add(head);
  groupBox(group, [0.08, 0.025, 0.26], [-0.02, 0.02, 0.16], materials.glass);
  groupBox(group, [0.08, 0.025, 0.26], [-0.02, 0.02, -0.16], materials.glass);
  const baseY = pos[1];
  animatedProps.push((dt) => {
    group.position.y = baseY + Math.sin(performance.now() / 520 + yaw) * 0.018;
    head.rotation.y = Math.sin(performance.now() / 700 + yaw) * 0.45;
    group.rotation.y += Math.sin(performance.now() / 1600 + yaw) * dt * 0.15;
  });
}

function loadTexture(url: string) {
  const loader = new THREE.TextureLoader();
  loader.setCrossOrigin("anonymous");
  return new Promise<THREE.Texture>((resolve, reject) => {
    loader.load(url, resolve, undefined, reject);
  });
}

async function loadAlpeccaTexture(folder: string) {
  const webpUrl = `${alpeccaAssetRoot}/${folder}/spritesheet.webp`;
  try {
    return { texture: await loadTexture(webpUrl), source: "webp" };
  } catch {
    return { texture: await loadTexture(`${alpeccaAssetRoot}/${folder}/spritesheet.png`), source: "png" };
  }
}

async function loadAlpeccaVisualMeta(folder: string): Promise<AlpeccaVisualMeta> {
  try {
    const response = await fetch(`${alpeccaAssetRoot}/${folder}/visual.json`);
    if (!response.ok) throw new Error("missing visual metadata");
    return (await response.json()) as AlpeccaVisualMeta;
  } catch {
    return { visualScale: 1, spriteY: 0.93 };
  }
}

function alpeccaPoseVisibleHeight(name: AlpeccaAnimationName) {
  if (name === "sit") return 1.34;
  if (name === "kneel") return 1.24;
  if (name === "crouch") return 1.08;
  if (name.startsWith("sleep")) return 0.58;
  return alpeccaStandingVisibleHeight;
}

function alpeccaHeightClass(name: AlpeccaAnimationName) {
  if (name === "sit") return "sit";
  if (name === "kneel") return "kneel";
  if (name === "crouch") return "crouch";
  if (name.startsWith("sleep")) return "sleep";
  return "standing";
}

function isAlpeccaStandingHeightClass(name: AlpeccaAnimationName) {
  return alpeccaHeightClass(name) === "standing";
}

function alpeccaStandingVisualLock() {
  const idle = alpecca.animations.get("idleDown");
  const baseScale = idle?.visualScale || 0.88;
  const visualScale = THREE.MathUtils.clamp(baseScale * alpeccaStandingPresentationScale, 0.98, 1.16);
  const spriteY = THREE.MathUtils.clamp(idle?.spriteY || 0.86, 0.78, 1.08);
  return { visualScale, spriteY };
}

function shouldLockAlpeccaStandingVisual(name: AlpeccaAnimationName) {
  return isAlpeccaStandingHeightClass(name);
}

function relockAlpeccaStandingVisuals() {
  const lock = alpeccaStandingVisualLock();
  for (const [name, animation] of alpecca.animations) {
    if (name === "idleDown" || !shouldLockAlpeccaStandingVisual(name)) continue;
    animation.visualScale = lock.visualScale;
    animation.spriteY = lock.spriteY;
  }
  const current = alpecca.animations.get(alpecca.state);
  if (current && shouldLockAlpeccaStandingVisual(alpecca.state)) {
    alpecca.visualScale = current.visualScale;
    alpecca.spriteY = current.spriteY;
  }
}

function alpeccaMaxVisualScale(name: AlpeccaAnimationName) {
  if (name === "sleep") return 1.45;
  if (name === "kneel" || name === "crouch") return 1.42;
  if (name.startsWith("sleep") || name.startsWith("wave") || name.startsWith("jump") || name === "climb") return 1.48;
  return 1.34;
}

function normalizeAlpeccaVisual(name: AlpeccaAnimationName, meta: AlpeccaVisualMeta, frameSize: number) {
  if (shouldLockAlpeccaStandingVisual(name) && name !== "idleDown") {
    return alpeccaStandingVisualLock();
  }

  const bounds = meta.alphaBounds;
  const alphaHeight = bounds?.h;
  const alphaBottom = Number.isFinite(bounds?.y) && Number.isFinite(bounds?.h) ? bounds!.y! + bounds!.h! : undefined;
  const resolvedFrameSize = Math.max(1, frameSize || meta.frameSize || 512);
  const maxVisualScale = alpeccaMaxVisualScale(name);

  if (Number.isFinite(alphaHeight) && alphaHeight! > 0 && Number.isFinite(alphaBottom)) {
    const targetHeight = alpeccaPoseVisibleHeight(name);
    const visualScale = targetHeight / (alpeccaSpritePlaneSize * (alphaHeight! / resolvedFrameSize));
    const spriteY =
      alpeccaGroundClearance +
      visualScale * alpeccaSpritePlaneSize * (alphaBottom! / resolvedFrameSize - 0.5);
    return {
      visualScale: THREE.MathUtils.clamp(visualScale, 0.58, maxVisualScale),
      spriteY: THREE.MathUtils.clamp(spriteY, 0.34, 1.18),
    };
  }

  return {
    visualScale: THREE.MathUtils.clamp(Number.isFinite(meta.visualScale) ? meta.visualScale! : 1, 0.58, maxVisualScale),
    spriteY: THREE.MathUtils.clamp(Number.isFinite(meta.spriteY) ? meta.spriteY! : 0.93, 0.34, 1.18),
  };
}

function alpeccaAnimationSourceFamily(folder: string) {
  if (folder.startsWith("iso_")) return "iso";
  if (folder.startsWith("gpt16_")) return "gpt16";
  if (folder.startsWith("gpt3d_")) return "gpt3d";
  if (folder.startsWith("gpt_")) return "gpt";
  return folder.replace(/\s+/g, "_").split("_")[0] || "legacy";
}

function classifyAlpeccaAnimationSource(name: AlpeccaAnimationName, folder: string, meta: AlpeccaVisualMeta): { family: string; status: AlpeccaSourceStatus; flagged: boolean } {
  const family = alpeccaAnimationSourceFamily(folder);
  const metadataFlagged = Boolean(meta.proportion?.flagged);
  const nativeLeftWalk =
    name === "walkLeft" || name === "walkNorthwest" || name === "walkSouthwest";
  if (folder.startsWith("gpt3d_walk_")) return { family, status: "needs-regeneration", flagged: true };
  if (name.startsWith("walk") && family === "iso") return { family, status: "approved", flagged: false };
  if (nativeLeftWalk && family === "gpt16") return { family, status: "runtime-ok", flagged: metadataFlagged };
  if (name.startsWith("walk") && family === "gpt16") return { family, status: meta.mirroredFrom ? "runtime-ok" : "qa-only", flagged: metadataFlagged };
  if (name.startsWith("run") || name === "dash" || name.startsWith("jump") || name === "climb") return { family, status: "qa-only", flagged: metadataFlagged };
  return { family, status: metadataFlagged ? "runtime-ok" : "approved", flagged: metadataFlagged };
}

function alpeccaMatrixActionForState(name: AlpeccaAnimationName, talking: boolean): AlpeccaMatrixAction {
  if (talking || name === "talkDown" || alpecca.intent === "replying") return "talk";
  if (alpecca.intent === "listening" || alpecca.intent === "thinking") return "listen";
  if (name.startsWith("walk")) return "walk";
  if (name.startsWith("wave") || name === "wave") return "wave";
  if (name.startsWith("sleep") || name === "sleep") return "sleep";
  if (name === "sit") return "rest";
  if (name === "crouch") return "careful";
  if (name === "kneel" || name === "point" || name === "pickup") return "inspect";
  return "idle";
}

function alpeccaMatrixAssetKey(loadedKey: string, matrix: AlpeccaViewMatrixState, frameCount: number) {
  const mirrorPart = matrix.flipX ? "mirrored" : "native";
  const framesPart = frameCount > 0 ? `${frameCount}f` : "pending";
  return `${loadedKey}_${mirrorPart}_${framesPart}`;
}

function localAlpeccaRuntimeMatrixRecord(action: AlpeccaMatrixAction, matrix: AlpeccaViewMatrixState): AlpeccaRuntimeMatrixRecord {
  const state = alpeccaMatrixFallbackStates[action][matrix.horizontal];
  const config = alpeccaAnimationConfig[state];
  const animation = alpecca.animations.get(state);
  const sourceInfo = animation
    ? { family: animation.sourceFamily, status: animation.sourceStatus }
    : classifyAlpeccaAnimationSource(state, config.folder, {});
  return {
    key: `${action}_${matrix.vertical}_${matrix.horizontal}`,
    action,
    verticalTier: matrix.vertical,
    horizontalTier: matrix.horizontal,
    state,
    folder: animation?.folder ?? config.folder,
    frameCount: animation?.frames.length ?? 0,
    sourceFamily: sourceInfo.family,
    approvalStatus: sourceInfo.status,
    heightClass: alpeccaHeightClass(state),
    visualScale: animation?.visualScale,
    spriteY: animation?.spriteY,
    footAnchor: "bottom-center",
    contactFrameIndexes: action === "walk" ? [0, 4, 8, 12] : [],
    layerPlan: normalizeAlpeccaLayerPlan(undefined, action),
    depthProxy: "fallback-alpha-silhouette-plane",
    notes: "Runtime local fallback. Regenerate matrix-specific art and rebuild runtime_matrix_manifest.json to replace this.",
  };
}

function resolveAlpeccaRuntimeMatrixRecord(action: AlpeccaMatrixAction, matrix: AlpeccaViewMatrixState): { record: AlpeccaRuntimeMatrixRecord; resolution: AlpeccaMatrixResolution } {
  const sectorKey = alpeccaSector16RuntimeKey(matrix.sector16);
  const exactKey = `${action}_${matrix.vertical}_${sectorKey}`;
  const exactRecord = alpeccaRuntimeMatrixRecords.get(exactKey);
  if (exactRecord) return { record: exactRecord, resolution: "exact" };

  const eyeKey = `${action}_eye_${sectorKey}`;
  const eyeRecord = alpeccaRuntimeMatrixRecords.get(eyeKey);
  if (eyeRecord) return { record: eyeRecord, resolution: "vertical-fallback" };

  const horizontalExactKey = `${action}_${matrix.vertical}_${matrix.horizontal}`;
  const horizontalExactRecord = alpeccaRuntimeMatrixRecords.get(horizontalExactKey);
  if (horizontalExactRecord) return { record: horizontalExactRecord, resolution: "vertical-fallback" };

  const horizontalEyeKey = `${action}_eye_${matrix.horizontal}`;
  const horizontalEyeRecord = alpeccaRuntimeMatrixRecords.get(horizontalEyeKey);
  if (horizontalEyeRecord) return { record: horizontalEyeRecord, resolution: "vertical-fallback" };

  return { record: localAlpeccaRuntimeMatrixRecord(action, matrix), resolution: "local-fallback" };
}

function alpeccaBuildMatrixAssetProbe(name: AlpeccaAnimationName, animation: AlpeccaAnimation | undefined, matrix: AlpeccaViewMatrixState, talking: boolean): AlpeccaMatrixAssetProbe {
  const action = alpeccaMatrixActionForState(name, talking);
  const requestedKey = `${action}_${matrix.vertical}_${alpeccaSector16RuntimeKey(matrix.sector16)}`;
  const { record, resolution } = resolveAlpeccaRuntimeMatrixRecord(action, matrix);
  const resolvedAnimation = alpecca.animations.get(record.state);
  const folder = resolvedAnimation?.folder ?? record.folder;
  const frameCount = resolvedAnimation?.frames.length ?? record.frameCount ?? 0;
  const assetKey = alpeccaMatrixAssetKey(record.key, matrix, frameCount);
  return {
    action,
    assetKey,
    requestedKey,
    loadedKey: record.key,
    fallbackState: record.state,
    folder,
    frameCount,
    sourceFamily: resolvedAnimation?.sourceFamily ?? record.sourceFamily,
    approvalStatus: resolvedAnimation?.sourceStatus ?? record.approvalStatus,
    manifestStatus: alpeccaRuntimeMatrixManifestStatus,
    resolution,
    layerPlan: (record.layerPlan?.roles || []).join("+") || "base-body",
    footAnchor: record.footAnchor || "bottom-center",
    contactFrames: (record.contactFrameIndexes || []).join(","),
    depthProxy: record.depthProxy || "alpha-silhouette-plane",
  };
}

async function loadAlpeccaAnimation(name: AlpeccaAnimationName, folder: string, secondsPerFrame = 1 / 12, loop = true) {
  const response = await fetch(`${alpeccaAssetRoot}/${folder}/atlas.json`);
  if (!response.ok) throw new Error(`Could not load Alpecca ${folder} atlas`);
  const atlas = (await response.json()) as SpriteAtlas;
  const { texture, source: textureSource } = await loadAlpeccaTexture(folder);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.magFilter = THREE.NearestFilter;
  texture.minFilter = THREE.NearestFilter;
  texture.wrapS = THREE.ClampToEdgeWrapping;
  texture.wrapT = THREE.ClampToEdgeWrapping;
  texture.generateMipmaps = false;
  texture.anisotropy = Math.min(4, renderer.capabilities.getMaxAnisotropy());

  const frames = Object.keys(atlas.frames)
    .sort((a, b) => Number(a) - Number(b))
    .map((key) => atlas.frames[key])
    .filter(Boolean);

  const visualMeta = await loadAlpeccaVisualMeta(folder);
  const frameSize = atlas.meta?.frame_size?.h ?? frames[0]?.h ?? visualMeta.frameSize ?? 512;
  const visual = normalizeAlpeccaVisual(name, visualMeta, frameSize);
  const sourceInfo = classifyAlpeccaAnimationSource(name, folder, visualMeta);

  alpecca.animations.set(name, {
    texture,
    frames,
    frameIndex: 0,
    elapsed: 0,
    secondsPerFrame,
    folder,
    textureSource,
    sourceFamily: sourceInfo.family,
    sourceStatus: sourceInfo.status,
    sourceFlagged: sourceInfo.flagged,
    visualScale: visual.visualScale,
    spriteY: visual.spriteY,
    heightClass: alpeccaHeightClass(name),
    silhouetteWidth: Number(visualMeta.proportion?.maxFrameWidth ?? visualMeta.alphaBounds?.w ?? 0),
    legWidthRatio: Number(visualMeta.proportion?.lowerBodyWidthRatio ?? 0),
    loop,
    completed: false,
  });
  if (name === "idleDown") relockAlpeccaStandingVisuals();
}

async function ensureAlpeccaAnimation(name: AlpeccaAnimationName) {
  if (alpecca.animations.has(name) || alpecca.loading.has(name)) return;
  const config = alpeccaAnimationConfig[name];
  alpecca.loading.add(name);
  try {
    await loadAlpeccaAnimation(name, config.folder, config.secondsPerFrame, config.loop ?? true);
    if (alpecca.state === name) setAlpeccaAnimation(name);
  } catch (error) {
    console.warn(`Alpecca ${name} animation failed to load.`, error);
  } finally {
    alpecca.loading.delete(name);
  }
}

function applyAlpeccaFrame(animation: AlpeccaAnimation) {
  const frame = animation.frames[animation.frameIndex];
  const image = animation.texture.image as HTMLImageElement | undefined;
  if (!frame || !image?.width || !image?.height) return;

  animation.texture.repeat.set(frame.w / image.width, frame.h / image.height);
  animation.texture.offset.set(frame.x / image.width, 1 - (frame.y + frame.h) / image.height);
  if (alpecca.depthProxy && alpecca.depthProxy.material.map !== animation.texture) alpecca.depthProxy.material.map = animation.texture;
  if (alpecca.glitchRed && alpecca.glitchRed.material.map !== animation.texture) alpecca.glitchRed.material.map = animation.texture;
  if (alpecca.glitchCyan && alpecca.glitchCyan.material.map !== animation.texture) alpecca.glitchCyan.material.map = animation.texture;
  updateAlpeccaProfileFrame(animation, frame, image);
}

function applyAlpeccaGhostFrame(animation: AlpeccaAnimation) {
  const ghost = alpecca.transitionGhost;
  const material = alpecca.transitionGhostMaterial;
  const frame = animation.frames[animation.frameIndex];
  const image = animation.texture.image as HTMLImageElement | undefined;
  if (!ghost || !material || !frame || !image?.width || !image?.height) return;

  const previousMap = material.map;
  const texture = animation.texture.clone();
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.magFilter = THREE.NearestFilter;
  texture.minFilter = THREE.NearestFilter;
  texture.wrapS = THREE.ClampToEdgeWrapping;
  texture.wrapT = THREE.ClampToEdgeWrapping;
  texture.generateMipmaps = false;
  texture.repeat.set(frame.w / image.width, frame.h / image.height);
  texture.offset.set(frame.x / image.width, 1 - (frame.y + frame.h) / image.height);
  texture.needsUpdate = true;

  material.map = texture;
  material.opacity = 0.18;
  material.needsUpdate = true;
  if (previousMap && previousMap !== texture) previousMap.dispose();
  if (alpecca.sprite) {
    ghost.scale.copy(alpecca.sprite.scale);
    ghost.position.copy(alpecca.sprite.position);
    ghost.rotation.copy(alpecca.sprite.rotation);
  }
  ghost.visible = true;
  alpecca.transitionTimer = alpecca.transitionDuration;
}

async function loadAlpeccaChatExpressions() {
  try {
    const response = await fetch(`${alpeccaChatExpressionRoot}/expressions.json`);
    if (!response.ok) throw new Error("missing Alpecca chat expression atlas");
    alpeccaChatExpressionAtlas = (await response.json()) as AlpeccaChatExpressionAtlas;
    updateAlpeccaChatExpressionPortrait(true);
  } catch (error) {
    console.warn("Alpecca chat expressions failed to load.", error);
  }
}

function alpeccaChatExpressionByLabel(...labels: Array<string | undefined>) {
  if (!alpeccaChatExpressionAtlas) return undefined;
  return labels
    .filter((label): label is string => Boolean(label))
    .map((label) => alpeccaChatExpressionAtlas?.frames.find((frame) => frame.label === label))
    .find(Boolean);
}

function alpeccaProfileExpressionSet() {
  const mood = alpeccaAiMood.toLowerCase();
  if (alpeccaProfileMode === "thinking") {
    return {
      key: "thinking",
      listen: ["attentive", "neutral_soft", "neutral"],
      talk: ["small_o", "surprised_o", "talk_o"],
    };
  }
  if (alpeccaProfileMode === "observing") {
    return {
      key: "observing",
      listen: ["attentive", "curious", "soft_smile", "neutral"],
      talk: ["small_o", "soft_talk", "talk_o"],
    };
  }
  if (alpeccaProfileMode === "self") {
    return {
      key: "self",
      listen: ["blush_pout", "embarrassed_hand", "neutral_soft"],
      talk: ["soft_talk", "small_o", "talk_round"],
    };
  }
  if (alpeccaActiveProfileFeature === "memory") {
    return {
      key: "memory",
      listen: ["attentive", "neutral_soft", "quiet"],
      talk: ["soft_talk", "talk_o", "small_o"],
    };
  }
  if (alpeccaActiveProfileFeature === "studio") {
    return {
      key: "studio",
      listen: ["soft_smile", "playful", "neutral_soft"],
      talk: ["happy_talk", "smile_open", "soft_talk"],
    };
  }
  if (alpeccaActiveProfileFeature === "home") {
    return {
      key: "home",
      listen: ["warm_smile", "gentle_smile", "soft_smile"],
      talk: ["soft_talk", "talk_round", "smile_open"],
    };
  }
  if (alpeccaAiAwaitingReply) {
    return {
      key: "thinking-reply",
      listen: ["attentive", "neutral_soft", "neutral"],
      talk: ["small_o", "talk_o", "soft_talk"],
    };
  }
  if (["angry", "frustrated"].some((word) => mood.includes(word))) {
    return {
      key: "angry",
      listen: ["annoyed", "angry", "deadpan"],
      talk: ["angry_yell", "talk_round", "talk_o"],
    };
  }
  if (["worried", "anxious", "fearful"].some((word) => mood.includes(word))) {
    return {
      key: "worried",
      listen: ["concerned", "sad", "neutral_soft"],
      talk: ["worried_talk", "small_o", "soft_talk"],
    };
  }
  if (["sleepy", "withdrawn", "lonely", "low"].some((word) => mood.includes(word))) {
    return {
      key: "sleepy",
      listen: ["sleepy", "tired", "quiet"],
      talk: ["soft_talk", "small_o", "talk_o"],
    };
  }
  if (["joyful", "playful", "happy", "affectionate"].some((word) => mood.includes(word))) {
    return {
      key: "happy",
      listen: ["warm_smile", "soft_smile", "gentle_smile"],
      talk: ["happy_talk", "smile_open", "soft_talk"],
    };
  }
  if (["shy", "embarrassed"].some((word) => mood.includes(word))) {
    return {
      key: "shy",
      listen: ["blush_pout", "blush_wink", "embarrassed_hand"],
      talk: ["soft_talk", "small_o", "talk_round"],
    };
  }
  return {
    key: "neutral",
    listen: ["soft_smile", "neutral", "neutral_soft"],
    talk: ["talk_round", "soft_talk", "talk_o", "small_o"],
  };
}

function chooseAlpeccaChatExpression(talking: boolean) {
  const atlas = alpeccaChatExpressionAtlas;
  if (!atlas) return undefined;

  const now = performance.now();
  const expressionSet = alpeccaProfileExpressionSet();
  const closedFrame = alpeccaChatExpressionByLabel(...expressionSet.listen);

  const blinkWindow = now % 4300;
  if (!talking && blinkWindow > 4100 && atlas.blinkCycle.length > 0) {
    const index = atlas.blinkCycle[Math.floor(now / 4300) % atlas.blinkCycle.length];
    alpeccaProfileTalkFrame = "";
    alpeccaProfileTalkFrameTier = -1;
    alpeccaProfileHeldExpression = undefined;
    return atlas.frames[index] ?? atlas.frames[0];
  }

  if (!talking) {
    alpeccaProfileTalkFrame = "";
    alpeccaProfileTalkFrameTier = -1;
    alpeccaProfileHeldExpression = undefined;
    return closedFrame ?? atlas.frames[0];
  }

  const mouthTier = alpecca.mouthOpen > 0.58 ? 2 : alpecca.mouthOpen > 0.24 ? 1 : 0;
  const talkFrames = [
    closedFrame,
    alpeccaChatExpressionByLabel(expressionSet.talk[0], expressionSet.talk[1], expressionSet.talk[2], expressionSet.talk[3]),
    alpeccaChatExpressionByLabel(expressionSet.talk[1], expressionSet.talk[2], expressionSet.talk[0], expressionSet.talk[3]),
  ];
  const nextFrame = talkFrames[mouthTier] ?? talkFrames[1] ?? closedFrame ?? atlas.frames[0];
  const talkKey = `${expressionSet.key}:${nextFrame?.label ?? ""}`;
  const minSwitchMs = mouthTier === 0 ? 95 : 135;
  if (
    alpeccaProfileHeldExpression &&
    alpeccaProfileTalkFrameKey === expressionSet.key &&
    alpeccaProfileTalkFrameTier === mouthTier &&
    now - alpeccaProfileLastTalkFrameAt < minSwitchMs
  ) {
    alpeccaProfileTalkFrame = alpeccaProfileHeldExpression.label;
    return alpeccaProfileHeldExpression;
  }

  alpeccaProfileTalkFrameKey = expressionSet.key;
  alpeccaProfileTalkFrameTier = mouthTier;
  alpeccaProfileLastTalkFrameAt = now;
  alpeccaProfileHeldExpression = nextFrame;
  alpeccaProfileTalkFrame = nextFrame?.label ?? "";
  return nextFrame;
}

function updateAlpeccaChatExpressionPortrait(force = false) {
  const atlas = alpeccaChatExpressionAtlas;
  if (!atlas || alpeccaChat.classList.contains("hidden")) return false;
  const frame = chooseAlpeccaChatExpression(isAlpeccaTalking());
  if (!frame) return false;
  alpeccaProfileMouthMode = "atlas-frames";
  if (!force && frame.index === alpeccaChatExpressionFrameIndex) return true;

  const rows = Math.ceil(atlas.frames.length / Math.max(1, atlas.columns));
  const avatarSize = Math.max(58, Math.min(alpeccaProfileAvatar.clientWidth || 104, alpeccaProfileAvatar.clientHeight || 104));
  const sourceFrameSize = atlas.frameSize || Math.max(frame.w, frame.h, 512);
  const scale = (avatarSize * 1.34) / sourceFrameSize;
  const frameDisplaySize = sourceFrameSize * scale;
  const offsetX = frame.x * scale + Math.max(0, (frameDisplaySize - avatarSize) / 2);
  const offsetY = frame.y * scale + Math.max(0, (frameDisplaySize - avatarSize) / 2);
  alpeccaProfileAvatar.classList.add("expression-atlas");
  alpeccaProfileAvatar.style.backgroundImage = `image-set(url("${alpeccaChatExpressionRoot}/${atlas.image}") type("image/webp"), url("${alpeccaChatExpressionRoot}/${atlas.fallbackImage}") type("image/png"))`;
  alpeccaProfileAvatar.style.backgroundSize = `${atlas.columns * atlas.frameSize * scale}px ${rows * atlas.frameSize * scale}px`;
  alpeccaProfileAvatar.style.backgroundPosition = `-${offsetX}px -${offsetY}px`;
  alpeccaChatExpressionFrameIndex = frame.index;
  alpeccaChatExpressionLabel = frame.label;
  alpeccaProfileState.textContent = alpeccaProfileDetailLabel(`expression:${frame.label}`);
  return true;
}

function updateAlpeccaProfileFrame(animation: AlpeccaAnimation, frame: SpriteFrame, image: HTMLImageElement) {
  if (alpeccaChat.classList.contains("hidden")) return;
  if (updateAlpeccaChatExpressionPortrait()) return;
  alpeccaProfileMouthMode = "fallback-overlay";
  alpeccaProfileTalkFrame = "";
  const imageUrl = image.currentSrc || image.src;
  if (!imageUrl) return;
  const avatarSize = Math.max(58, Math.min(alpeccaProfileAvatar.clientWidth || 104, alpeccaProfileAvatar.clientHeight || 104));
  const sourceFrameSize = Math.max(frame.w, frame.h, 512);
  const scale = (avatarSize * 1.34) / sourceFrameSize;
  alpeccaProfileAvatar.classList.remove("expression-atlas");
  alpeccaProfileAvatar.style.backgroundImage = `url("${imageUrl}")`;
  alpeccaProfileAvatar.style.backgroundSize = `${image.width * scale}px ${image.height * scale}px`;
  alpeccaProfileAvatar.style.backgroundPosition = `-${frame.x * scale}px -${frame.y * scale}px`;
  alpeccaProfileState.textContent = alpeccaProfileDetailLabel(`sprite:${animation.folder}`);
}

void loadAlpeccaChatExpressions();

function isAlpeccaOneShotState(name: AlpeccaAnimationName) {
  return alpeccaAnimationConfig[name]?.loop === false;
}

function estimateAlpeccaAnimationDuration(animation: AlpeccaAnimation) {
  return animation.frames.reduce((sum, frame) => sum + Math.max((frame.duration ?? 1) * animation.secondsPerFrame, 0.035), 0);
}

function shouldHoldCurrentAlpeccaAnimation(next: AlpeccaAnimationName) {
  if (alpecca.state === next || alpecca.animationLockTimer <= 0) return false;
  const current = alpecca.animations.get(alpecca.state);
  if (!current || current.loop || current.completed) return false;
  return true;
}

function completedAlpeccaOneShot(name = alpecca.state) {
  const animation = alpecca.animations.get(name);
  return !!animation && !animation.loop && animation.completed;
}

function settleCompletedAlpeccaGesture(holdState: AlpeccaAnimationName = "idleDown") {
  if (!completedAlpeccaOneShot()) return false;
  setAlpeccaAnimation(holdState, true);
  return true;
}

function calmAlpeccaMotionState(name: AlpeccaAnimationName): AlpeccaAnimationName {
  if (name === "dash" || name === "run") return "walkSide";
  if (name === "runDown") return "walkDown";
  if (name === "runUp") return "walkUp";
  if (name === "runSide") return "walkSide";
  if (name === "runNortheast") return "walkNortheast";
  if (name === "runSoutheast") return "walkSoutheast";
  return name;
}

function queueAlpeccaAnimationLoad(name: AlpeccaAnimationName, urgent = false) {
  if (alpecca.animations.has(name) || alpecca.loading.has(name)) return;
  const existingIndex = alpeccaPreloadQueue.indexOf(name);
  if (existingIndex >= 0) alpeccaPreloadQueue.splice(existingIndex, 1);
  if (urgent) {
    alpeccaPreloadQueue.unshift(name);
    alpeccaPreloadTimer = Math.min(alpeccaPreloadTimer, 0.02);
  } else {
    alpeccaPreloadQueue.push(name);
  }
}

function alpeccaFallbackForMissingAnimation(name: AlpeccaAnimationName): AlpeccaAnimationName | null {
  if (name.startsWith("walk")) {
    if (alpecca.animations.has("walk")) return "walk";
    if (alpecca.animations.has("idleDown")) return "idleDown";
    return alpecca.animations.has("idle") ? "idle" : null;
  }
  if (name.startsWith("idle")) return alpecca.animations.has("idle") ? "idle" : null;
  if (name.startsWith("run")) return alpecca.animations.has("walk") ? "walk" : alpecca.animations.has("idle") ? "idle" : null;
  if (name.startsWith("jump") || name === "dash" || name === "climb") return alpecca.animations.has("idleDown") ? "idleDown" : "idle";
  return null;
}

function shouldGlitchAlpeccaTransition(previous: AlpeccaAnimationName, next: AlpeccaAnimationName) {
  if (previous === next) return false;
  const expressive = (state: AlpeccaAnimationName) =>
    state === "dance" ||
    state === "victory" ||
    state === "dash" ||
    state === "climb" ||
    state === "jump" ||
    state.startsWith("jump");
  return expressive(previous) || expressive(next);
}

function setAlpeccaAnimation(name: AlpeccaAnimationName, force = false, allowRareMotion = false) {
  name = allowRareMotion ? name : calmAlpeccaMotionState(name);
  if (!force && shouldHoldCurrentAlpeccaAnimation(name)) return;
  const previousState = alpecca.state;
  const previousAnimation = alpecca.animations.get(previousState);
  const carryWalkPhase =
    previousAnimation &&
    previousState !== name &&
    previousState.startsWith("walk") &&
    name.startsWith("walk") &&
    previousAnimation.frames.length > 0;
  const previousFrame = carryWalkPhase ? previousAnimation.frames[previousAnimation.frameIndex] : undefined;
  const previousFrameDuration = carryWalkPhase ? alpeccaFrameDuration(previousAnimation, previousFrame) : 1;
  const previousWalkPhase = carryWalkPhase
    ? (previousAnimation.frameIndex + THREE.MathUtils.clamp(previousAnimation.elapsed / Math.max(previousFrameDuration, 0.001), 0, 0.98)) /
      previousAnimation.frames.length
    : 0;
  const animation = alpecca.animations.get(name);
  if (alpecca.state === name && animation && alpecca.material.map === animation.texture) return;
  if (!animation) {
    const config = alpeccaAnimationConfig[name];
    queueAlpeccaAnimationLoad(name, true);
    const fallbackName = alpeccaFallbackForMissingAnimation(name);
    if (fallbackName && fallbackName !== name && alpecca.animations.has(fallbackName)) {
      setAlpeccaAnimation(fallbackName, true);
      alpecca.activeFolder = config.folder;
    alpeccaProfileState.textContent = alpeccaProfileDetailLabel(`loading ${config.folder}`);
      return;
    }
    alpecca.state = name;
    alpecca.activeFolder = config.folder;
    setAlpeccaSourcePlate(sourcePlateForAlpeccaState(name));
    alpeccaProfileState.textContent = alpeccaProfileDetailLabel(`loading ${alpecca.activeFolder}`);
    return;
  }

  alpecca.state = name;
  alpecca.activeFolder = animation.folder;
  if (
    previousAnimation &&
    previousState !== name &&
    !previousState.startsWith("walk") &&
    !name.startsWith("walk") &&
    !isAlpeccaWalkQaMode()
  ) {
    applyAlpeccaGhostFrame(previousAnimation);
  }
  if (shouldGlitchAlpeccaTransition(previousState, name) && !shouldLockAlpeccaStandingVisual(name)) alpecca.glitchTimer = Math.max(alpecca.glitchTimer, 0.22);
  if (carryWalkPhase) {
    const phaseFrame = previousWalkPhase * animation.frames.length;
    animation.frameIndex = THREE.MathUtils.clamp(Math.floor(phaseFrame), 0, Math.max(0, animation.frames.length - 1));
    animation.elapsed = (phaseFrame - animation.frameIndex) * alpeccaFrameDuration(animation, animation.frames[animation.frameIndex]);
  } else {
    animation.frameIndex = 0;
    animation.elapsed = 0;
  }
  animation.completed = false;
  alpecca.animationLockTimer = isAlpeccaOneShotState(name)
    ? THREE.MathUtils.clamp(estimateAlpeccaAnimationDuration(animation) * 0.82, 0.42, 1.8)
    : 0;
  alpecca.material.map = animation.texture;
  if (alpecca.depthProxy) alpecca.depthProxy.material.map = animation.texture;
  if (alpecca.glitchRed) alpecca.glitchRed.material.map = animation.texture;
  if (alpecca.glitchCyan) alpecca.glitchCyan.material.map = animation.texture;
  if (alpecca.silhouette) alpecca.silhouette.material.map = animation.texture;
  alpecca.material.needsUpdate = true;
  alpecca.visualScale = animation.visualScale;
  alpecca.spriteY = animation.spriteY;
  applyAlpeccaVisualTransform(0, true);
  setAlpeccaSourcePlate(sourcePlateForAlpeccaState(name));
  applyAlpeccaFrame(animation);
  if (alpeccaVrmEmbodiment && isAlpeccaVrm3D()) {
    alpeccaVrmEmbodiment.setSpriteState(name, alpecca.moving, isAlpeccaTalking());
  }
}

function targetAlpeccaBodyLean() {
  if (!alpecca.moving || !alpecca.state.startsWith("walk")) return 0;
  const horizontal =
    alpecca.screenDirection === "left" ||
    alpecca.screenDirection === "right" ||
    alpecca.screenDirection === "northwest" ||
    alpecca.screenDirection === "northeast" ||
    alpecca.screenDirection === "southwest" ||
    alpecca.screenDirection === "southeast";
  const diagonal =
    alpecca.screenDirection === "northwest" ||
    alpecca.screenDirection === "northeast" ||
    alpecca.screenDirection === "southwest" ||
    alpecca.screenDirection === "southeast";
  const sideLean = horizontal ? (diagonal ? 0.018 : 0.028) : 0;
  const leftFacing =
    alpecca.screenDirection === "left" || alpecca.screenDirection === "northwest" || alpecca.screenDirection === "southwest";
  const signedSideLean = sideLean * (leftFacing ? 1 : -1);
  const strideLean = Math.sin(alpecca.stridePhase + Math.PI / 4) * 0.014;
  return THREE.MathUtils.clamp(signedSideLean + strideLean, -0.04, 0.04);
}

function applyAlpeccaVisualTransform(dt = 0, snap = false) {
  if (!alpecca.sprite) return;
  const walking = alpecca.moving && alpecca.state.startsWith("walk");
  if (shouldLockAlpeccaStandingVisual(alpecca.state)) {
    const lock = alpeccaStandingVisualLock();
    alpecca.visualScale = lock.visualScale;
    alpecca.spriteY = lock.spriteY;
  }
  if (snap) {
    alpecca.displayScale = alpecca.visualScale;
    alpecca.displaySpriteY = alpecca.spriteY;
  } else if (dt > 0) {
    alpecca.displayScale = THREE.MathUtils.damp(alpecca.displayScale, alpecca.visualScale, 12, dt);
    alpecca.displaySpriteY = THREE.MathUtils.damp(alpecca.displaySpriteY, alpecca.spriteY, 12, dt);
  }
  const targetStrideX = alpecca.moving && alpecca.state.startsWith("walk") ? Math.sin(alpecca.stridePhase) * 0.024 : 0;
  alpecca.strideX = snap ? targetStrideX : THREE.MathUtils.damp(alpecca.strideX, targetStrideX, 12, dt);
  const targetLean = targetAlpeccaBodyLean();
  alpecca.bodyLean = snap ? targetLean : THREE.MathUtils.damp(alpecca.bodyLean, targetLean, 14, dt);
  const targetWalkBob = walking ? Math.sin(alpecca.stridePhase * 2) * 0.003 : 0;
  alpecca.walkBob = snap ? targetWalkBob : THREE.MathUtils.damp(alpecca.walkBob, targetWalkBob, 18, dt);
  const signedX = alpecca.flipX ? -alpecca.displayScale : alpecca.displayScale;
  alpecca.sprite.scale.set(signedX, alpecca.displayScale, alpeccaSpriteDepthScale);
  alpecca.sprite.position.x = alpecca.strideX;
  alpecca.sprite.position.y = alpecca.displaySpriteY + alpecca.walkBob;
  alpecca.sprite.rotation.z = alpecca.bodyLean;
  if (alpecca.depthProxy) {
    alpecca.depthProxy.scale.set(signedX, alpecca.displayScale, alpeccaSpriteDepthScale);
    alpecca.depthProxy.position.copy(alpecca.sprite.position);
    alpecca.depthProxy.rotation.copy(alpecca.sprite.rotation);
  }
  if (alpecca.silhouette) {
    const silhouetteOpacity = alpecca.state.startsWith("sleep") ? 0.08 : alpecca.moving ? 0.18 : 0.13;
    alpecca.silhouette.material.opacity = dt > 0 ? THREE.MathUtils.damp(alpecca.silhouette.material.opacity, silhouetteOpacity, 10, dt) : silhouetteOpacity;
    alpecca.silhouette.scale.set(signedX * 1.045, alpecca.displayScale * 1.018, alpeccaSpriteDepthScale);
    alpecca.silhouette.position.set(alpecca.strideX + (alpecca.flipX ? 0.022 : -0.022) - alpecca.bodyLean * 0.18, alpecca.displaySpriteY - 0.035 + alpecca.walkBob * 0.45, -0.018);
    alpecca.silhouette.rotation.z = alpecca.bodyLean * 0.72;
    alpecca.silhouette.visible = alpecca.silhouette.material.opacity > 0.015;
  }
  if (alpecca.glitchRed) alpecca.glitchRed.rotation.z = alpecca.bodyLean;
  if (alpecca.glitchCyan) alpecca.glitchCyan.rotation.z = alpecca.bodyLean;
  if (alpecca.glitchScanline) alpecca.glitchScanline.rotation.z = alpecca.bodyLean;
  if (alpecca.transitionGhost && alpecca.transitionGhostMaterial) {
    if (alpecca.transitionTimer > 0) {
      alpecca.transitionTimer = Math.max(0, alpecca.transitionTimer - dt);
      const fade = alpecca.transitionTimer / alpecca.transitionDuration;
      alpecca.transitionGhostMaterial.opacity = fade * 0.18;
      alpecca.transitionGhost.position.y = alpecca.sprite.position.y;
      alpecca.transitionGhost.position.x = alpecca.sprite.position.x - (alpecca.flipX ? -0.016 : 0.016) * fade;
      alpecca.transitionGhost.scale.set(signedX * (1 + fade * 0.01), alpecca.displayScale, alpeccaSpriteDepthScale);
      alpecca.transitionGhost.rotation.z = alpecca.bodyLean * 0.85;
      alpecca.transitionGhost.visible = alpecca.transitionGhostMaterial.opacity > 0.01;
    } else {
      alpecca.transitionGhostMaterial.opacity = 0;
      alpecca.transitionGhost.visible = false;
    }
  }
  if (alpecca.heightRuler) {
    alpecca.heightRuler.visible = alpecca.showcaseTimer > 0 || isAlpeccaWalkQaMode();
    alpecca.heightRuler.position.x = alpecca.flipX ? 0.86 : -0.86;
  }
}

function shortestAngleDelta(from: number, to: number) {
  return THREE.MathUtils.euclideanModulo(to - from + Math.PI, Math.PI * 2) - Math.PI;
}

function dampAngle(from: number, to: number, lambda: number, dt: number) {
  if (dt <= 0) return to;
  const t = 1 - Math.exp(-lambda * dt);
  return from + shortestAngleDelta(from, to) * t;
}

function applyAlpeccaBillboardYaw(dt = 0, snap = false) {
  alpeccaLastViewMatrix = computeAlpeccaViewMatrix();
  if (isAlpeccaVrm3D()) {
    // The 3D body faces by group rotation (groundYaw); billboard skew would twist it.
    alpecca.billboardYaw = snap ? 0 : dampAngle(alpecca.billboardYaw, 0, 8, dt);
    return;
  }
  const viewCamera = alpeccaPresentationCamera();
  const toCameraX = viewCamera.position.x - alpecca.group.position.x;
  const toCameraZ = viewCamera.position.z - alpecca.group.position.z;
  if (Math.abs(toCameraX) + Math.abs(toCameraZ) < 0.001) return;

  const cameraYaw = Math.atan2(toCameraX, toCameraZ);
  const fullLocalYaw = shortestAngleDelta(alpecca.group.rotation.y, cameraYaw);
  const clampRad = THREE.MathUtils.degToRad(alpeccaLastViewMatrix.billboardClampDeg || 16);
  const clampedLocalYaw = THREE.MathUtils.clamp(fullLocalYaw, -clampRad, clampRad);
  const volumetricYawStrength =
    alpeccaLastViewMatrix.volumeZone === "near-body" ? 0.18 : alpeccaLastViewMatrix.volumeZone === "interaction-shell" ? 0.28 : 0.38;
  const localYaw = clampedLocalYaw * volumetricYawStrength;
  alpecca.billboardYaw = snap ? localYaw : dampAngle(alpecca.billboardYaw, localYaw, 8, dt);

  const visualObjects = [
    alpecca.depthProxy,
    alpecca.silhouette,
    alpecca.sprite,
    alpecca.glitchRed,
    alpecca.glitchCyan,
    alpecca.glitchScanline,
    alpecca.headLook,
    alpecca.hitTarget,
  ].filter(Boolean) as THREE.Object3D[];
  for (const object of visualObjects) object.rotation.y = alpecca.billboardYaw;
}

function setAlpeccaSpriteFlip(flipX: boolean) {
  alpecca.flipX = flipX;
  applyAlpeccaVisualTransform();
}

function setAlpeccaSpriteFlipFromScreenX(screenX: number) {
  if (screenX < -0.18) setAlpeccaSpriteFlip(true);
  else if (screenX > 0.18) setAlpeccaSpriteFlip(false);
}

function focusAlpecca(seconds = 2.2, animation: AlpeccaAnimationName = "idleDown", allowRareMotion = false) {
  alpecca.attentionTimer = Math.max(alpecca.attentionTimer, seconds);
  alpeccaLiveAttentionTimer = Math.max(alpeccaLiveAttentionTimer, seconds);
  setAlpeccaIntent(isAlpeccaTalking() ? "replying" : alpeccaAiAwaitingReply ? "thinking" : "listening", "player");
  setAlpeccaActivity(isAlpeccaTalking() ? "Alpecca is replying to you." : "Alpecca is focused on you.", "think", Math.min(seconds, 4));
  alpecca.moving = false;
  alpecca.walkIntent = false;
  alpecca.walkPauseTimer = Math.max(alpecca.walkPauseTimer, Math.min(seconds, 2.2));
  alpecca.dwellTimer = Math.max(alpecca.dwellTimer, Math.min(seconds, 2.2));
  alpecca.lastMovedDistance = 0;
  setAlpeccaSpriteFlip(false);
  setAlpeccaAnimation(animation, true, allowRareMotion);
}

function updateAlpeccaVoiceReadout() {
  const original = (alpeccaVoiceName || "af_heart") === "af_heart" && (alpeccaVoiceProfile || "").includes("original");
  alpeccaVoiceIdentityEl.textContent = "Alpecca's voice";
  const style = alpeccaVoiceStyle && !["content", "offline"].includes(alpeccaVoiceStyle.toLowerCase()) ? alpeccaVoiceStyle : "present";
  const warmthText = alpeccaVoiceWarmth ? `, warmth ${alpeccaVoiceWarmth}` : "";
  alpeccaVoiceModulationEl.textContent = original
    ? `${alpeccaVoiceSessionState}: ${style}${warmthText}`
    : `${alpeccaVoiceSessionState}: Original voice warming`;
}

function numberHeader(response: Response, name: string, fallback = 0) {
  const value = Number(response.headers.get(name));
  return Number.isFinite(value) ? value : fallback;
}

function applyAlpeccaVoiceEmotionHeaders(response: Response) {
  const warmth = THREE.MathUtils.clamp(numberHeader(response, "X-Alpecca-Voice-Warmth", Number(alpeccaVoiceWarmth) || 0.5), 0, 1);
  const breath = THREE.MathUtils.clamp(numberHeader(response, "X-Alpecca-Voice-Breath", Number(alpeccaVoiceBreath) || 0.25), 0, 1);
  const speed = THREE.MathUtils.clamp(numberHeader(response, "X-Alpecca-Voice-Speed", Number(alpeccaVoiceSpeed) || 1), 0.6, 1.3);
  const rate = THREE.MathUtils.clamp(numberHeader(response, "X-Alpecca-Voice-Rate", Number(alpeccaVoiceRate) || 100) / 100, 0.6, 1.3);
  const primary = (response.headers.get("X-Alpecca-Voice-Primary") || alpeccaVoicePrimary || "content").toLowerCase();
  const style = (response.headers.get("X-Alpecca-Voice-Style") || alpeccaVoiceStyle || "present").toLowerCase();
  const anxious = ["anxious", "worried", "tight", "careful"].some((word) => primary.includes(word) || style.includes(word));
  const sleepy = ["sleepy", "drowsy", "withdrawn", "lonely"].some((word) => primary.includes(word) || style.includes(word));
  const joyful = ["joyful", "playful", "bright", "spark"].some((word) => primary.includes(word) || style.includes(word));
  alpeccaVoiceEmotionState = {
    love: THREE.MathUtils.clamp(Math.max(alpeccaAiState.love ?? 0.45, 0.24 + warmth * 0.72 + (joyful ? 0.08 : 0)), 0, 1),
    compassion: THREE.MathUtils.clamp(Math.max(alpeccaAiState.compassion ?? 0.45, 0.22 + warmth * 0.58 + breath * 0.18), 0, 1),
    fear: THREE.MathUtils.clamp(Math.max(anxious ? 0.62 : 0, alpeccaAiState.fear ?? 0) + (style.includes("tight") ? 0.08 : 0), 0, 1),
    energy: THREE.MathUtils.clamp(sleepy ? 0.18 : 0.24 + (speed + rate - 1.2) * 0.55 + (joyful ? 0.16 : 0) - breath * 0.12, 0, 1),
  };
  alpeccaVoiceEmotionTimer = Math.max(alpeccaVoiceEmotionTimer, 5.2);
  document.body.dataset.alpeccaVoiceAffect = `${primary}:${style}`;
  updateAlpeccaMoodPanel();
}

function captureAlpeccaVoiceHeaders(response: Response) {
  alpeccaVoiceEngine = response.headers.get("X-Alpecca-TTS-Engine") || alpeccaVoiceEngine || "server";
  alpeccaVoiceName = response.headers.get("X-Alpecca-Voice") || alpeccaVoiceName || "af_heart";
  alpeccaVoiceProfile = response.headers.get("X-Alpecca-Voice-Profile") || alpeccaVoiceProfile || "af_heart_original_modulated";
  alpeccaVoicePreview = response.headers.get("X-Alpecca-Voice-Preview") || "current";
  alpeccaVoicePrimary = response.headers.get("X-Alpecca-Voice-Primary") || alpeccaVoicePrimary || "content";
  alpeccaVoiceTempo = response.headers.get("X-Alpecca-Voice-Tempo") || alpeccaVoiceTempo || "measured";
  alpeccaVoiceRate = response.headers.get("X-Alpecca-Voice-Rate") || alpeccaVoiceRate || "100";
  alpeccaVoiceSpeed = response.headers.get("X-Alpecca-Voice-Speed") || alpeccaVoiceSpeed || "1";
  alpeccaVoiceStyle = response.headers.get("X-Alpecca-Voice-Style") || alpeccaVoiceStyle || "present";
  alpeccaVoiceWarmth = response.headers.get("X-Alpecca-Voice-Warmth") || alpeccaVoiceWarmth || "";
  alpeccaVoiceBreath = response.headers.get("X-Alpecca-Voice-Breath") || alpeccaVoiceBreath || "";
  alpeccaVoiceModulationStrength = response.headers.get("X-Alpecca-Voice-Modulation-Strength") || alpeccaVoiceModulationStrength || "";
  applyAlpeccaVoiceEmotionHeaders(response);
  updateAlpeccaVoiceReadout();
}

function unlockAlpeccaVoicePlayback() {
  if (alpeccaVoicePlaybackUnlocked) return;
  const AudioContextCtor = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!AudioContextCtor) return;
  try {
    alpeccaVoiceAudioContext = alpeccaVoiceAudioContext || new AudioContextCtor();
    if (alpeccaVoiceAudioContext.state === "suspended") {
      void alpeccaVoiceAudioContext.resume()
        .then(() => {
          alpeccaVoicePlaybackUnlocked = true;
        })
        .catch(() => undefined);
    } else {
      alpeccaVoicePlaybackUnlocked = true;
    }
    const buffer = alpeccaVoiceAudioContext.createBuffer(1, 1, 22050);
    const source = alpeccaVoiceAudioContext.createBufferSource();
    source.buffer = buffer;
    source.connect(alpeccaVoiceAudioContext.destination);
    source.start(0);
  } catch {
    // Some mobile browsers reject audio unlock outside a direct tap. The next
    // explicit voice tap will try again.
  }
}

async function prepareAlpeccaVoiceAudio(
  text: string,
  preview: string,
  signal: AbortSignal,
) {
  const clean = text.trim();
  if (!clean) throw new Error("voice text is empty");
  const payload: { text: string; preview?: string; exact_text: boolean } = { text: clean, exact_text: true };
  if (preview) payload.preview = preview;
  const request = new AbortController();
  let timedOut = false;
  const forwardAbort = () => request.abort(signal.reason);
  if (signal.aborted) forwardAbort();
  else signal.addEventListener("abort", forwardAbort, { once: true });
  const timer = window.setTimeout(() => {
    timedOut = true;
    request.abort(new DOMException("Voice synthesis timed out.", "TimeoutError"));
  }, ALPECCA_TTS_REQUEST_TIMEOUT_MS);
  let response: Response;
  let blob: Blob;
  try {
    response = await alpeccaBackendFetch(alpeccaUrlWithParams(`${alpeccaAiBaseUrl}/tts`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: request.signal,
    });
    if (!response.ok || response.status === 204) {
      throw new Error(response.headers.get("X-Alpecca-TTS-Error") || "server voice unavailable");
    }
    blob = await response.blob();
    if (request.signal.aborted) throw request.signal.reason;
  } catch (error) {
    if (timedOut) throw new Error("voice synthesis timed out");
    throw error;
  } finally {
    window.clearTimeout(timer);
    signal.removeEventListener("abort", forwardAbort);
  }
  if (signal.aborted) throw new DOMException("Voice request was interrupted.", "AbortError");
  captureAlpeccaVoiceHeaders(response);
  const objectUrl = URL.createObjectURL(blob);
  const audio = new Audio(objectUrl);
  audio.setAttribute("playsinline", "true");
  alpeccaVoiceObjectUrl = objectUrl;
  alpeccaVoiceAudio = audio;
  return audio;
}

function releaseAlpeccaVoiceAudio(audio: HTMLAudioElement) {
  const objectUrl = audio.src;
  if (alpeccaVoiceAudio === audio) alpeccaVoiceAudio = null;
  if (objectUrl) {
    try {
      URL.revokeObjectURL(objectUrl);
    } catch {}
  }
  if (alpeccaVoiceObjectUrl === objectUrl) alpeccaVoiceObjectUrl = "";
}

function playAlpeccaVoice(
  text: string,
  preview = "",
  priority: AlpeccaSpeechPriority = "reply",
) {
  const clean = text.trim();
  const requestKey = `${preview || "current"}:${clean}`;
  if (!clean || (requestKey === alpeccaVoiceLastText && alpeccaVoiceSession.state !== "idle")) return;
  if (priority !== "proactive") {
    alpeccaVoiceSession.interrupt({ clearQueue: true, reason: `${priority} speech took focus` });
  }
  alpeccaVoiceLastText = requestKey;
  try {
    const speech = alpeccaVoiceSession.enqueueSpeech({
      label: priority,
      preparePlayback: ({ signal }) => prepareAlpeccaVoiceAudio(clean, preview, signal),
      releasePlayback: releaseAlpeccaVoiceAudio,
    });
    void speech.completion.then((result) => {
      if (alpeccaVoiceLastText === requestKey) alpeccaVoiceLastText = "";
      if (result.outcome === "completed") alpeccaVoicePlaybackUnlocked = true;
      if (result.outcome === "unavailable" && /notallowed|gesture/i.test(result.reason)) {
        appendAlpeccaLog("System", "Voice playback was blocked by this browser. Tap Hear voice once, then try again.");
      }
    });
  } catch (error) {
    if (error instanceof VoiceQueueFullError && priority === "proactive") return;
    alpeccaVoiceLastText = "";
    alpeccaVoiceSession.markUnavailable(error instanceof Error ? error.message : "voice queue unavailable");
  }
}

function startAlpeccaSpeech(
  text: string,
  preview = "",
  priority: AlpeccaSpeechPriority = "reply",
) {
  playAlpeccaVoice(text, preview, priority);
}

function isAlpeccaTalking() {
  return alpeccaAvatarPlaybackSignal.talking;
}

function updateAlpeccaVoiceEmotion(dt: number) {
  if (alpeccaVoiceEmotionTimer <= 0) return;
  alpeccaVoiceEmotionTimer = Math.max(0, alpeccaVoiceEmotionTimer - dt);
  if (alpeccaVoiceEmotionTimer === 0) {
    alpeccaVoiceEmotionState = {};
    document.body.dataset.alpeccaVoiceAffect = "";
    updateAlpeccaMoodPanel();
  }
}

function isAlpeccaAnimationName(value: string): value is AlpeccaAnimationName {
  return alpeccaAllAnimationStates.includes(value as AlpeccaAnimationName);
}

function screenDirectionForAlpeccaAnimation(name: AlpeccaAnimationName): AlpeccaScreenDirection | null {
  if (name === "walkDown" || name === "runDown" || name === "idleDown" || name === "talkDown" || name === "waveDown" || name === "sleepDown") return "down";
  if (name === "walkUp" || name === "runUp" || name === "idleUp" || name === "waveUp" || name === "sleepUp") return "up";
  if (name === "walkLeft") return "left";
  if (name === "walkSide" || name === "runSide" || name === "idleSide") return "right";
  if (name === "walkNortheast" || name === "runNortheast" || name === "idleNortheast" || name === "waveNortheast" || name === "sleepNortheast") return "northeast";
  if (name === "walkNorthwest") return "northwest";
  if (name === "walkSoutheast" || name === "runSoutheast" || name === "idleSoutheast" || name === "sleepSoutheast" || name === "jumpSoutheast") return "southeast";
  if (name === "walkSouthwest") return "southwest";
  if (name === "walk" || name === "run" || name === "dash" || name === "jump" || name === "jumpSide") return "right";
  if (name === "jumpDown") return "down";
  if (name === "jumpUp") return "up";
  return null;
}

function shouldFlipAlpeccaAnimation(name: AlpeccaAnimationName) {
  const direction = screenDirectionForAlpeccaAnimation(name);
  return alpeccaShouldFlipForDirection(name, direction);
}

function alpeccaAnimationUsesNativeLeftArt(name: AlpeccaAnimationName) {
  const folder = alpeccaAnimationConfig[name]?.folder ?? "";
  return /(^|_)left($|_)/.test(folder);
}

function alpeccaShouldFlipForDirection(name: AlpeccaAnimationName, direction: AlpeccaScreenDirection | null) {
  if (direction !== "left" && direction !== "northwest" && direction !== "southwest") return false;
  return !alpeccaAnimationUsesNativeLeftArt(name);
}

function showcaseAlpeccaAnimation(name: AlpeccaAnimationName, seconds = 2.6) {
  alpecca.showcaseState = name;
  alpecca.showcaseTimer = Math.max(alpecca.showcaseTimer, seconds);
  alpecca.attentionTimer = 0;
  alpeccaLiveAttentionTimer = 0;
  alpecca.expressiveTimer = 0;
  alpecca.waveTimer = 0;
  alpecca.moving = false;
  alpecca.walkIntent = false;
  alpecca.lastMovedDistance = 0;
  const debugDirection = screenDirectionForAlpeccaAnimation(name);
  if (debugDirection) {
    alpecca.screenDirection = debugDirection;
    alpecca.directionCandidate = debugDirection;
    alpecca.directionCandidateFrames = 0;
  }
  setAlpeccaSpriteFlip(shouldFlipAlpeccaAnimation(name));
  setAlpeccaAnimation(name, true, true);
}

function addAlpeccaGroundShadow() {
  const material = new THREE.MeshBasicMaterial({
    color: "#050606",
    transparent: true,
    opacity: 0.24,
    depthWrite: false,
  });
  const shadow = new THREE.Mesh(new THREE.PlaneGeometry(0.82, 0.34), material);
  shadow.name = "Alpecca contact shadow";
  shadow.rotation.x = -Math.PI / 2;
  shadow.position.set(alpecca.group.position.x, 0.018, alpecca.group.position.z);
  shadow.renderOrder = 2;
  scene.add(shadow);
  alpecca.shadow = shadow;

  const chromaMaterial = new THREE.MeshBasicMaterial({
    color: "#55d6ff",
    transparent: true,
    opacity: 0.12,
    depthWrite: false,
  });
  const chroma = new THREE.Mesh(new THREE.PlaneGeometry(1.05, 0.42), chromaMaterial);
  chroma.name = "Alpecca chromatic occlusion";
  chroma.rotation.x = -Math.PI / 2;
  chroma.position.set(alpecca.group.position.x + 0.035, 0.019, alpecca.group.position.z - 0.02);
  chroma.renderOrder = 3;
  scene.add(chroma);
  alpecca.chromaShadow = chroma;

  const reflectionMaterial = new THREE.MeshBasicMaterial({
    color: "#dff4f2",
    transparent: true,
    opacity: 0,
    depthWrite: false,
  });
  const reflection = new THREE.Mesh(new THREE.PlaneGeometry(0.72, 0.24), reflectionMaterial);
  reflection.name = "Alpecca floor reflection anchor";
  reflection.rotation.x = -Math.PI / 2;
  reflection.position.set(alpecca.group.position.x, 0.0205, alpecca.group.position.z);
  reflection.renderOrder = 4;
  scene.add(reflection);
  alpecca.floorReflection = reflection;

  const presenceMaterial = new THREE.MeshBasicMaterial({
    color: "#7de7ff",
    transparent: true,
    opacity: 0,
    depthWrite: false,
  });
  const presenceGlow = new THREE.Mesh(new THREE.PlaneGeometry(1.35, 0.58), presenceMaterial);
  presenceGlow.name = "Alpecca spatial presence glow";
  presenceGlow.rotation.x = -Math.PI / 2;
  presenceGlow.position.set(alpecca.group.position.x, 0.021, alpecca.group.position.z);
  presenceGlow.renderOrder = 4;
  scene.add(presenceGlow);
  alpecca.presenceGlow = presenceGlow;

  const presenceLight = new THREE.PointLight("#b9f4ff", 0, 3.4, 2.3);
  presenceLight.name = "Alpecca spatial presence light";
  presenceLight.castShadow = false;
  presenceLight.position.set(alpecca.group.position.x, 1.28, alpecca.group.position.z);
  scene.add(presenceLight);
  alpecca.presenceLight = presenceLight;

  const footGeometry = new THREE.PlaneGeometry(0.24, 0.095);
  const makeFootMaterial = () =>
    new THREE.MeshBasicMaterial({
      color: "#050606",
      transparent: true,
      opacity: 0,
      depthWrite: false,
    });
  const leftFoot = new THREE.Mesh(footGeometry, makeFootMaterial());
  leftFoot.name = "Alpecca left foot contact shadow";
  leftFoot.rotation.x = -Math.PI / 2;
  leftFoot.renderOrder = 5;
  scene.add(leftFoot);
  alpecca.leftFootShadow = leftFoot;

  const rightFoot = new THREE.Mesh(footGeometry, makeFootMaterial());
  rightFoot.name = "Alpecca right foot contact shadow";
  rightFoot.rotation.x = -Math.PI / 2;
  rightFoot.renderOrder = 5;
  scene.add(rightFoot);
  alpecca.rightFootShadow = rightFoot;
}

function addAlpeccaDepthLayers(sprite: THREE.Mesh<THREE.PlaneGeometry, THREE.MeshBasicMaterial>) {
  const depthProxyMaterial = new THREE.MeshBasicMaterial({
    transparent: false,
    alphaTest: 0.18,
    depthWrite: true,
    depthTest: true,
    side: THREE.DoubleSide,
  });
  depthProxyMaterial.colorWrite = false;
  depthProxyMaterial.map = sprite.material.map;
  const depthProxy = new THREE.Mesh(sprite.geometry, depthProxyMaterial);
  depthProxy.name = "Alpecca alpha depth proxy";
  depthProxy.renderOrder = 4;
  depthProxy.position.copy(sprite.position);
  depthProxy.scale.copy(sprite.scale);
  alpecca.group.add(depthProxy);
  alpecca.depthProxy = depthProxy;

  const transitionMaterial = new THREE.MeshBasicMaterial({
    transparent: true,
    opacity: 0,
    alphaTest: 0.08,
    depthWrite: false,
    side: THREE.DoubleSide,
  });
  transitionMaterial.map = sprite.material.map;
  const transitionGhost = new THREE.Mesh(sprite.geometry, transitionMaterial);
  transitionGhost.name = "Alpecca walk transition ghost";
  transitionGhost.renderOrder = 7;
  transitionGhost.visible = false;
  transitionGhost.position.copy(sprite.position);
  transitionGhost.scale.copy(sprite.scale);
  alpecca.group.add(transitionGhost);
  alpecca.transitionGhost = transitionGhost;
  alpecca.transitionGhostMaterial = transitionMaterial;

  const silhouetteMaterial = new THREE.MeshBasicMaterial({
    color: "#091012",
    transparent: true,
    opacity: 0.12,
    alphaTest: 0.08,
    depthWrite: false,
    side: THREE.DoubleSide,
  });
  silhouetteMaterial.map = sprite.material.map;
  const silhouette = new THREE.Mesh(sprite.geometry, silhouetteMaterial);
  silhouette.name = "Alpecca depth silhouette";
  silhouette.renderOrder = 6;
  silhouette.position.set(-0.02, sprite.position.y - 0.035, -0.018);
  silhouette.scale.setScalar(1.03);
  alpecca.group.add(silhouette);
  alpecca.silhouette = silhouette;
}

function addAlpeccaHeightRuler() {
  const ruler = new THREE.Group();
  ruler.name = "Alpecca 5ft 7in proportion ruler";
  const material = new THREE.MeshBasicMaterial({ color: "#9fe8ff", transparent: true, opacity: 0.72, depthWrite: false });
  const markMaterial = new THREE.MeshBasicMaterial({ color: "#ffffff", transparent: true, opacity: 0.85, depthWrite: false });
  const height = alpeccaStandingVisibleHeight;
  const line = new THREE.Mesh(new THREE.BoxGeometry(0.018, height, 0.012), material);
  line.position.set(0, alpeccaGroundClearance + height * 0.5, 0);
  const bottom = new THREE.Mesh(new THREE.BoxGeometry(0.22, 0.014, 0.012), markMaterial);
  bottom.position.set(0, alpeccaGroundClearance, 0);
  const top = new THREE.Mesh(new THREE.BoxGeometry(0.22, 0.014, 0.012), markMaterial);
  top.position.set(0, alpeccaGroundClearance + height, 0);
  ruler.add(line, bottom, top);
  ruler.position.set(-0.86, 0, 0.018);
  ruler.renderOrder = 10;
  ruler.visible = false;
  alpecca.group.add(ruler);
  alpecca.heightRuler = ruler;
}

function updateAlpeccaFootShadows(dt: number) {
  const left = alpecca.leftFootShadow;
  const right = alpecca.rightFootShadow;
  if (!left || !right) return;

  const resting = alpecca.state === "sit" || alpecca.state.startsWith("sleep");
  const crouched = alpecca.state === "crouch" || alpecca.state === "kneel";
  const yaw = alpecca.groundYaw;
  const forwardX = Math.sin(yaw);
  const forwardZ = Math.cos(yaw);
  const rightX = Math.cos(yaw);
  const rightZ = -Math.sin(yaw);
  const stride = alpecca.moving && alpecca.state.startsWith("walk") ? Math.sin(alpecca.stridePhase) : 0;
  const strideDepth = alpecca.moving ? 0.115 : 0;
  const stanceWidth = crouched ? 0.18 : 0.145;
  const baseX = alpecca.group.position.x;
  const baseZ = alpecca.group.position.z;
  const y = 0.023;

  left.position.set(baseX - rightX * stanceWidth + forwardX * stride * strideDepth, y, baseZ - rightZ * stanceWidth + forwardZ * stride * strideDepth);
  right.position.set(
    baseX + rightX * stanceWidth - forwardX * stride * strideDepth,
    y,
    baseZ + rightZ * stanceWidth - forwardZ * stride * strideDepth,
  );

  left.rotation.z = dampAngle(left.rotation.z, -yaw, 12, dt);
  right.rotation.z = dampAngle(right.rotation.z, -yaw, 12, dt);

  const leftLoaded = stride >= 0;
  const hidden = resting || alpecca.state.startsWith("sleep");
  const baseOpacity = crouched ? 0.12 : 0.095;
  const movingBoost = alpecca.moving ? 0.075 : 0;
  const leftTarget = hidden ? 0 : baseOpacity + (leftLoaded ? movingBoost : 0);
  const rightTarget = hidden ? 0 : baseOpacity + (!leftLoaded ? movingBoost : 0);
  left.material.opacity = THREE.MathUtils.damp(left.material.opacity, leftTarget, 12, dt);
  right.material.opacity = THREE.MathUtils.damp(right.material.opacity, rightTarget, 12, dt);
  left.visible = left.material.opacity > 0.01;
  right.visible = right.material.opacity > 0.01;

  const leftScale = hidden ? 0.4 : 0.92 + (leftLoaded && alpecca.moving ? 0.2 : 0);
  const rightScale = hidden ? 0.4 : 0.92 + (!leftLoaded && alpecca.moving ? 0.2 : 0);
  left.scale.set(THREE.MathUtils.damp(left.scale.x, leftScale, 10, dt), THREE.MathUtils.damp(left.scale.y, 0.92, 10, dt), 1);
  right.scale.set(THREE.MathUtils.damp(right.scale.x, rightScale, 10, dt), THREE.MathUtils.damp(right.scale.y, 0.92, 10, dt), 1);
  alpecca.footContact = hidden ? "resting" : alpecca.moving ? (leftLoaded ? "left" : "right") : "idle";
  const contactTarget = hidden ? 0.16 : crouched ? 0.78 : alpecca.moving ? 0.86 : 0.58;
  alpecca.groundContactIntensity = THREE.MathUtils.damp(alpecca.groundContactIntensity, contactTarget, 9, dt);
  updateAlpeccaFloorReflection(dt, hidden, crouched);
}

function updateAlpeccaFloorReflection(dt: number, resting: boolean, crouched: boolean) {
  const reflection = alpecca.floorReflection;
  if (!reflection) return;

  const yaw = alpecca.groundYaw;
  const forwardX = Math.sin(yaw);
  const forwardZ = Math.cos(yaw);
  const room = officeRoomAtPosition(alpecca.group.position.x, alpecca.group.position.z);
  const targetColor = alpeccaFloorColor.set(featureColorForRoom(room.id));
  reflection.material.color.lerp(targetColor, THREE.MathUtils.clamp(dt * 3.5, 0, 1));

  const lift = resting ? 0.018 : crouched ? 0.026 : alpecca.moving ? 0.038 : 0.026;
  reflection.position.set(
    alpecca.group.position.x + forwardX * lift + alpecca.strideX * 0.38,
    0.0205,
    alpecca.group.position.z + forwardZ * lift,
  );
  reflection.rotation.z = dampAngle(reflection.rotation.z, -yaw, 9, dt);

  const baseOpacity = resting ? 0.025 : crouched ? 0.07 : alpecca.moving ? 0.095 : 0.065;
  const targetOpacity = baseOpacity * THREE.MathUtils.clamp(0.55 + alpecca.groundContactIntensity * 0.55, 0, 1);
  alpecca.floorReflectionIntensity = THREE.MathUtils.damp(alpecca.floorReflectionIntensity, targetOpacity, 8, dt);
  reflection.material.opacity = alpecca.floorReflectionIntensity;
  reflection.visible = reflection.material.opacity > 0.008;

  const length = resting ? 0.9 : crouched ? 0.76 : alpecca.moving ? 1.06 : 0.86;
  const width = crouched ? 0.88 : alpecca.moving ? 0.78 : 0.72;
  reflection.scale.set(THREE.MathUtils.damp(reflection.scale.x, width, 8, dt), THREE.MathUtils.damp(reflection.scale.y, length, 8, dt), 1);
}

function alpeccaPresenceTargetColor() {
  const mood = alpeccaAiMood.toLowerCase();
  if (mood.includes("anxious") || mood.includes("worried") || mood.includes("fear")) return alpeccaPresenceColor.set("#9fc8ff");
  if (mood.includes("sleepy") || mood.includes("withdrawn") || mood.includes("lonely")) return alpeccaPresenceColor.set("#c7d4e8");
  if (mood.includes("joyful") || mood.includes("playful") || mood.includes("affectionate")) return alpeccaPresenceColor.set("#b8fff1");
  return alpeccaPresenceColor.set(alpeccaAiStatus === "live" ? "#a8f4ff" : "#9adce6");
}

function updateAlpeccaSpatialPresence(dt: number, distanceToPlayer: number, playerEngaged: boolean) {
  const glow = alpecca.presenceGlow;
  const light = alpecca.presenceLight;
  if (!glow && !light) return;

  const thinking = alpeccaAiAwaitingReply || alpeccaLiveAttentionTimer > 0;
  const resting = alpecca.state === "sit" || alpecca.state.startsWith("sleep");
  const pulse = 0.5 + Math.sin(performance.now() / 520 + alpecca.group.position.x * 0.6) * 0.5;
  const distanceFocus = THREE.MathUtils.clamp(1 - distanceToPlayer / 4.8, 0, 1);
  const activeBoost = playerEngaged || thinking ? 0.055 : 0;
  const moveBoost = alpecca.moving ? 0.035 : 0;
  const targetPresence = resting ? 0.035 : 0.07 + activeBoost + moveBoost + (alpeccaAiStatus === "live" ? 0.02 : 0) + distanceFocus * 0.025;
  alpecca.presenceIntensity = THREE.MathUtils.damp(alpecca.presenceIntensity, targetPresence + pulse * 0.012, 8, dt);
  const color = alpeccaPresenceTargetColor();

  if (glow) {
    glow.position.set(alpecca.group.position.x, 0.0215, alpecca.group.position.z);
    glow.rotation.z = dampAngle(glow.rotation.z, -alpecca.groundYaw, 8, dt);
    glow.material.opacity = THREE.MathUtils.damp(glow.material.opacity, alpecca.presenceIntensity, 9, dt);
    glow.material.color.lerp(color, THREE.MathUtils.clamp(dt * 4, 0, 1));
    const width = 1.0 + (alpecca.moving ? 0.18 : 0.04) + pulse * 0.035;
    const depth = 0.92 + (playerEngaged ? 0.12 : 0) + pulse * 0.025;
    glow.scale.set(THREE.MathUtils.damp(glow.scale.x, width, 8, dt), THREE.MathUtils.damp(glow.scale.y, depth, 8, dt), 1);
    glow.visible = glow.material.opacity > 0.012;
  }

  if (light) {
    light.position.set(alpecca.group.position.x, 1.24, alpecca.group.position.z);
    light.color.lerp(color, THREE.MathUtils.clamp(dt * 4, 0, 1));
    light.intensity = THREE.MathUtils.damp(light.intensity, alpecca.presenceIntensity * 0.95, 7, dt);
    light.distance = playerEngaged || thinking ? 3.8 : 3.15;
  }
}

function addAlpeccaGlitchLayers(sprite: THREE.Mesh<THREE.PlaneGeometry, THREE.MeshBasicMaterial>) {
  const geometry = sprite.geometry;
  const scanlineCanvas = document.createElement("canvas");
  scanlineCanvas.width = 64;
  scanlineCanvas.height = 64;
  const scanlineCtx = scanlineCanvas.getContext("2d");
  if (scanlineCtx) {
    scanlineCtx.clearRect(0, 0, 64, 64);
    scanlineCtx.fillStyle = "rgba(180, 255, 255, 0.26)";
    for (let y = 0; y < 64; y += 5) scanlineCtx.fillRect(0, y, 64, 1);
  }
  const scanlineTexture = new THREE.CanvasTexture(scanlineCanvas);
  scanlineTexture.wrapS = THREE.RepeatWrapping;
  scanlineTexture.wrapT = THREE.RepeatWrapping;
  const redMaterial = new THREE.MeshBasicMaterial({
    color: "#ff4b6e",
    transparent: true,
    opacity: 0,
    alphaTest: 0.08,
    depthWrite: false,
    side: THREE.DoubleSide,
  });
  const cyanMaterial = new THREE.MeshBasicMaterial({
    color: "#4be4ff",
    transparent: true,
    opacity: 0,
    alphaTest: 0.08,
    depthWrite: false,
    side: THREE.DoubleSide,
  });
  const scanlineMaterial = new THREE.MeshBasicMaterial({
    color: "#d9ffff",
    map: scanlineTexture,
    transparent: true,
    opacity: 0,
    alphaTest: 0.02,
    depthWrite: false,
    side: THREE.DoubleSide,
    blending: THREE.AdditiveBlending,
  });
  const red = new THREE.Mesh(geometry, redMaterial);
  const cyan = new THREE.Mesh(geometry, cyanMaterial);
  const scanline = new THREE.Mesh(geometry, scanlineMaterial);
  red.name = "Alpecca red glitch layer";
  cyan.name = "Alpecca cyan glitch layer";
  scanline.name = "Alpecca scanline shimmer layer";
  red.position.copy(sprite.position);
  cyan.position.copy(sprite.position);
  scanline.position.copy(sprite.position);
  red.renderOrder = 8;
  cyan.renderOrder = 9;
  scanline.renderOrder = 10;
  alpecca.group.add(red, cyan, scanline);
  alpecca.glitchRed = red;
  alpecca.glitchCyan = cyan;
  alpecca.glitchScanline = scanline;
}

function addAlpeccaHeadLook() {
  const group = new THREE.Group();
  group.name = "Alpecca head look tracker";
  group.position.set(0, 1.63, 0.026);
  const material = new THREE.MeshBasicMaterial({
    color: "#9ff3ff",
    transparent: true,
    opacity: 0,
    depthWrite: false,
    side: THREE.DoubleSide,
  });
  const left = new THREE.Mesh(new THREE.CircleGeometry(0.028, 12), material);
  const right = new THREE.Mesh(new THREE.CircleGeometry(0.028, 12), material);
  left.name = "left head-look glint";
  right.name = "right head-look glint";
  left.position.set(-0.075, 0, 0);
  right.position.set(0.075, 0, 0);
  const mouthMaterial = new THREE.MeshBasicMaterial({
    color: "#332134",
    transparent: true,
    opacity: 0,
    depthWrite: false,
    side: THREE.DoubleSide,
  });
  const mouth = new THREE.Mesh(new THREE.PlaneGeometry(0.082, 0.026), mouthMaterial);
  mouth.name = "Alpecca talking mouth";
  mouth.position.set(0, -0.125, 0.008);
  mouth.renderOrder = 12;
  group.add(left, right, mouth);
  alpecca.group.add(group);
  alpecca.headLook = group;
  alpecca.headLookMaterial = material;
  alpecca.mouth = mouth;
  alpecca.mouthMaterial = mouthMaterial;
}

function updateAlpeccaHeadLook(distanceToPlayer: number, playerEngaged: boolean, dt: number) {
  if (!alpecca.headLook || !alpecca.headLookMaterial) return;
  if (isAlpeccaVrm3D()) {
    // The VRM drives gaze (lookAt) and visemes itself; the sprite overlays stay hidden.
    alpecca.headLook.visible = false;
    if (alpecca.mouth) alpecca.mouth.visible = false;
    return;
  }
  const talking = isAlpeccaTalking();
  const now = performance.now();
  const awareness = THREE.MathUtils.clamp(1 - distanceToPlayer / 5.2, 0, 1);
  const targetOpacity = talking ? 0.92 : playerEngaged ? 0.7 : awareness * 0.46;
  alpecca.headLookMaterial.opacity = THREE.MathUtils.damp(alpecca.headLookMaterial.opacity, targetOpacity, 8, dt);
  alpecca.headLook.visible = alpecca.headLookMaterial.opacity > 0.025 || talking;

  const toPlayer = alpeccaCandidate.copy(camera.position).sub(alpecca.group.position);
  toPlayer.y = 0;
  if (toPlayer.lengthSq() < 0.001) return;
  toPlayer.normalize();
  const facing = alpeccaSideStep.set(Math.sin(alpecca.group.rotation.y), 0, Math.cos(alpecca.group.rotation.y));
  const right = cameraRightFlat.set(facing.z, 0, -facing.x).normalize();
  const lookX = THREE.MathUtils.clamp(toPlayer.dot(right), -1, 1);
  alpecca.headLook.position.x = THREE.MathUtils.damp(alpecca.headLook.position.x, lookX * 0.13, 10, dt);
  const talkingNod = talking ? Math.sin(now / 135) * 0.022 + Math.sin(now / 260) * 0.012 : 0;
  const walkHeadBob = alpecca.moving && alpecca.state.startsWith("walk") ? Math.sin(alpecca.stridePhase * 2) * 0.012 : 0;
  alpecca.headLook.position.y = THREE.MathUtils.damp(alpecca.headLook.position.y, 1.63 + talkingNod + walkHeadBob, 10, dt);
  alpecca.headLook.rotation.z = THREE.MathUtils.damp(alpecca.headLook.rotation.z, -lookX * 0.12 + (talking ? Math.sin(now / 180) * 0.035 : 0), 10, dt);

  const mouthSignal = talking ? THREE.MathUtils.clamp(0.18 + Math.abs(Math.sin(now / 74)) * 0.64 + Math.abs(Math.sin(now / 137)) * 0.28, 0, 1) : 0;
  alpecca.mouthOpen = THREE.MathUtils.damp(alpecca.mouthOpen, mouthSignal, talking ? 18 : 12, dt);
  if (alpecca.mouth && alpecca.mouthMaterial) {
    alpecca.mouth.visible = alpecca.mouthOpen > 0.03 || talking;
    alpecca.mouthMaterial.opacity = THREE.MathUtils.damp(alpecca.mouthMaterial.opacity, talking ? 0.82 : 0, 16, dt);
    alpecca.mouth.scale.set(1 + alpecca.mouthOpen * 0.42, 0.28 + alpecca.mouthOpen * 1.95, 1);
    alpecca.mouth.position.y = -0.125 - alpecca.mouthOpen * 0.006;
  }
}

type AlpeccaScreenDirection = "right" | "left" | "down" | "up" | "northeast" | "northwest" | "southeast" | "southwest";

function alpeccaDirectionFamily(direction: AlpeccaScreenDirection) {
  if (direction === "left" || direction === "right") return "side";
  if (direction === "up" || direction === "down") return "vertical";
  return "diagonal";
}

function classifyAlpeccaWorldDirection(move: THREE.Vector3, fallback: AlpeccaScreenDirection = alpecca.screenDirection): AlpeccaScreenDirection {
  const x = move.x;
  const z = move.z;
  const absX = Math.abs(x);
  const absZ = Math.abs(z);
  if (Math.max(absX, absZ) < alpeccaDirectionDeadzone) return fallback;
  if (absX > absZ * alpeccaDirectionHorizontalBias) return x < 0 ? "left" : "right";
  if (z < -alpeccaDirectionDiagonalMin) return absX > 0.28 ? (x < 0 ? "northwest" : "northeast") : "up";
  if (z > alpeccaDirectionDiagonalMin) return absX > 0.28 ? (x < 0 ? "southwest" : "southeast") : "down";
  return x < 0 ? "left" : "right";
}

function classifyAlpeccaScreenDirection(move: THREE.Vector3, fallback: AlpeccaScreenDirection = alpecca.screenDirection): AlpeccaScreenDirection {
  camera.getWorldDirection(cameraForwardFlat);
  cameraForwardFlat.y = 0;
  if (cameraForwardFlat.lengthSq() < 0.0001) cameraForwardFlat.set(0, 0, -1);
  cameraForwardFlat.normalize();
  cameraRightFlat.set(-cameraForwardFlat.z, 0, cameraForwardFlat.x).normalize();

  const screenX = move.dot(cameraRightFlat);
  const screenY = move.dot(cameraForwardFlat);
  const absX = Math.abs(screenX);
  const absY = Math.abs(screenY);

  if (Math.max(absX, absY) < alpeccaDirectionDeadzone) return fallback;
  if (absX > absY * alpeccaDirectionHorizontalBias) return screenX < 0 ? "left" : "right";
  if (screenY > alpeccaDirectionDiagonalMin) return absX > 0.28 ? (screenX < 0 ? "northwest" : "northeast") : "up";
  if (screenY < -alpeccaDirectionDiagonalMin) return absX > 0.28 ? (screenX < 0 ? "southwest" : "southeast") : "down";
  return screenX < 0 ? "left" : "right";
}

function alpeccaWorldDirection(movement: THREE.Vector3, stable = true): AlpeccaScreenDirection {
  const move = movement.lengthSq() > 0.0001 ? movement : alpeccaLastWorldMove;
  if (movement.lengthSq() > 0.0001) alpeccaLastWorldMove.copy(movement).normalize();

  const rawDirection = classifyAlpeccaWorldDirection(move);

  if (!stable) {
    alpecca.screenDirection = rawDirection;
    alpecca.directionCandidate = rawDirection;
    alpecca.directionCandidateFrames = 0;
    return rawDirection;
  }

  if (rawDirection === alpecca.screenDirection) {
    alpecca.directionCandidate = rawDirection;
    alpecca.directionCandidateFrames = 0;
    return alpecca.screenDirection;
  }

  if (rawDirection !== alpecca.directionCandidate) {
    alpecca.directionCandidate = rawDirection;
    alpecca.directionCandidateFrames = 1;
  } else {
    alpecca.directionCandidateFrames += 1;
  }

  const currentFamily = alpeccaDirectionFamily(alpecca.screenDirection);
  const nextFamily = alpeccaDirectionFamily(rawDirection);
  const requiredFrames = currentFamily === nextFamily ? 6 : nextFamily === "diagonal" || currentFamily === "diagonal" ? 10 : 8;
  if (alpecca.directionCandidateFrames >= requiredFrames) {
    alpecca.screenDirection = rawDirection;
    alpecca.directionCandidateFrames = 0;
  }

  return alpecca.screenDirection;
}

function alpeccaScreenDirection(movement: THREE.Vector3, stable = true): AlpeccaScreenDirection {
  const move = movement.lengthSq() > 0.0001 ? movement : alpeccaLastMove;
  if (movement.lengthSq() > 0.0001) alpeccaLastMove.copy(movement).normalize();

  const rawDirection = classifyAlpeccaScreenDirection(move);

  if (!stable) {
    alpecca.screenDirection = rawDirection;
    alpecca.directionCandidate = rawDirection;
    alpecca.directionCandidateFrames = 0;
    return rawDirection;
  }

  if (rawDirection === alpecca.screenDirection) {
    alpecca.directionCandidate = rawDirection;
    alpecca.directionCandidateFrames = 0;
    return alpecca.screenDirection;
  }

  if (rawDirection !== alpecca.directionCandidate) {
    alpecca.directionCandidate = rawDirection;
    alpecca.directionCandidateFrames = 1;
  } else {
    alpecca.directionCandidateFrames += 1;
  }

  const currentFamily = alpeccaDirectionFamily(alpecca.screenDirection);
  const nextFamily = alpeccaDirectionFamily(rawDirection);
  const requiredFrames = currentFamily === nextFamily ? 6 : nextFamily === "diagonal" || currentFamily === "diagonal" ? 10 : 8;
  if (alpecca.directionCandidateFrames >= requiredFrames) {
    alpecca.screenDirection = rawDirection;
    alpecca.directionCandidateFrames = 0;
  }

  return alpecca.screenDirection;
}

function directionalAlpeccaAnimation(base: "idle" | "walk", movement: THREE.Vector3) {
  const direction = alpeccaWorldDirection(movement);
  const states = {
    idle: {
      right: "idleSide",
      left: "idleSide",
      down: "idleDown",
      up: "idleUp",
      northeast: "idleNortheast",
      northwest: "idleNortheast",
      southeast: "idleSoutheast",
      southwest: "idleSoutheast",
    },
    walk: {
      right: "walkSide",
      left: "walkLeft",
      down: "walkDown",
      up: "walkUp",
      northeast: "walkNortheast",
      northwest: "walkNorthwest",
      southeast: "walkSoutheast",
      southwest: "walkSouthwest",
    },
  } as const;
  const state = states[base][direction];
  setAlpeccaSpriteFlip(alpeccaShouldFlipForDirection(state, direction));
  return state;
}

function directionalAlpeccaWave(directionVector: THREE.Vector3): AlpeccaAnimationName {
  const direction = alpeccaScreenDirection(directionVector, false);
  if (direction === "up") return "waveUp";
  if (direction === "northeast" || direction === "northwest" || direction === "right" || direction === "left") return "waveNortheast";
  return "waveDown";
}

function directionalAlpeccaSleep(directionVector: THREE.Vector3): AlpeccaAnimationName {
  const direction = alpeccaScreenDirection(directionVector, false);
  if (direction === "up") return "sleepUp";
  if (direction === "northeast" || direction === "northwest") return "sleepNortheast";
  if (direction === "southeast" || direction === "southwest" || direction === "right" || direction === "left") return "sleepSoutheast";
  return "sleepDown";
}

function directionalAlpeccaJump(directionVector: THREE.Vector3): AlpeccaAnimationName {
  const direction = alpeccaScreenDirection(directionVector, false);
  if (direction === "up") return "jumpUp";
  if (direction === "down") return "jumpDown";
  if (direction === "southeast") return "jumpSoutheast";
  return "jumpSide";
}

function faceAlpeccaSpriteToPlayer(dx: number, dz: number) {
  const faceVector = alpeccaToPlayer.set(dx, 0, dz);
  if (faceVector.lengthSq() < 0.0001) return;
  const direction = alpeccaScreenDirection(faceVector, false);
  setAlpeccaSpriteFlip(alpeccaShouldFlipForDirection("talkDown", direction));
}

function advanceAlpeccaStride(dt: number) {
  if (!alpecca.moving || !alpecca.state.startsWith("walk")) return;
  const animation = alpecca.animations.get(alpecca.state);
  if (animation && animation.frames.length > 0) {
    const frameProgress = THREE.MathUtils.clamp(animation.elapsed / Math.max(alpeccaFrameDuration(animation, animation.frames[animation.frameIndex]), 0.001), 0, 1);
    alpecca.stridePhase = ((animation.frameIndex + frameProgress) / animation.frames.length) * Math.PI * 2;
    return;
  }
  if (dt > 0) alpecca.stridePhase += dt * alpeccaWalkFrameRate * 0.72;
}

function updateAlpeccaWalkPlayback(dt: number) {
  const walking = alpecca.moving && alpecca.state.startsWith("walk");
  const measuredSpeed = dt > 0 ? alpecca.lastMovedDistance / dt : 0;
  const qaLockedWalk = alpecca.showcaseTimer > 0 && alpecca.showcaseState.startsWith("walk");
  const targetRate = qaLockedWalk
    ? alpeccaWalkFrameRate
    : walking
      ? THREE.MathUtils.clamp(alpeccaWalkFrameRate * (measuredSpeed / alpeccaWalkReferenceSpeed), alpeccaWalkPlaybackMin, alpeccaWalkPlaybackMax)
      : alpeccaWalkFrameRate;
  alpecca.walkSpeed = measuredSpeed;
  alpecca.walkPlaybackRate = dt > 0 ? THREE.MathUtils.damp(alpecca.walkPlaybackRate, targetRate, 8, dt) : targetRate;
}

function alpeccaFrameDuration(animation: AlpeccaAnimation, frame: SpriteFrame | undefined) {
  const authoredDuration = Math.max((frame?.duration ?? 1) * animation.secondsPerFrame, 0.035);
  if (!alpecca.state.startsWith("walk")) return authoredDuration;
  const playbackRate = THREE.MathUtils.clamp(alpecca.walkPlaybackRate || alpeccaWalkFrameRate, alpeccaWalkPlaybackMin, alpeccaWalkPlaybackMax);
  return Math.max(authoredDuration * (alpeccaWalkFrameRate / playbackRate), 0.055);
}

function updateAlpeccaAnimation(dt: number) {
  const animation = alpecca.animations.get(alpecca.state);
  if (!animation || animation.frames.length === 0) {
    applyAlpeccaVisualTransform(dt);
    return;
  }

  if (alpecca.glitchTimer > 0) {
    alpecca.glitchTimer -= dt;
    const intensity = THREE.MathUtils.clamp(alpecca.glitchTimer / 0.34, 0, 1) * calmVisualMultiplier(true);
    const standing = shouldLockAlpeccaStandingVisual(alpecca.state);
    const effectStrength = standing ? 0.42 : 1;
    const jitter = Math.sin(performance.now() / 18) * 0.055 * intensity * effectStrength;
    if (alpecca.glitchRed) {
      alpecca.glitchRed.visible = true;
      alpecca.glitchRed.material.opacity = 0.32 * intensity * effectStrength;
      alpecca.glitchRed.position.set((alpecca.sprite?.position.x || 0) - 0.04 * effectStrength - jitter, alpecca.sprite?.position.y || alpecca.spriteY, 0.012);
      alpecca.glitchRed.scale.set(alpecca.sprite?.scale.x ?? alpecca.visualScale, alpecca.sprite?.scale.y ?? alpecca.visualScale, alpeccaSpriteDepthScale);
    }
    if (alpecca.glitchCyan) {
      alpecca.glitchCyan.visible = true;
      alpecca.glitchCyan.material.opacity = 0.28 * intensity * effectStrength;
      alpecca.glitchCyan.position.set((alpecca.sprite?.position.x || 0) + 0.04 * effectStrength + jitter, alpecca.sprite?.position.y || alpecca.spriteY, 0.014);
      alpecca.glitchCyan.scale.set(alpecca.sprite?.scale.x ?? alpecca.visualScale, alpecca.sprite?.scale.y ?? alpecca.visualScale, alpeccaSpriteDepthScale);
    }
    if (alpecca.glitchScanline) {
      const shimmer = 0.5 + Math.sin(performance.now() / 28) * 0.5;
      alpecca.glitchScanline.visible = true;
      alpecca.glitchScanline.material.opacity = (0.12 + shimmer * 0.08) * intensity * effectStrength;
      alpecca.glitchScanline.position.set((alpecca.sprite?.position.x || 0) + jitter * 0.22, alpecca.sprite?.position.y || alpecca.spriteY, 0.016);
      alpecca.glitchScanline.scale.set(alpecca.sprite?.scale.x ?? alpecca.visualScale, alpecca.sprite?.scale.y ?? alpecca.visualScale, alpeccaSpriteDepthScale);
      const map = alpecca.glitchScanline.material.map;
      if (map) {
        map.offset.y = (map.offset.y + dt * (0.8 + shimmer * 1.2)) % 1;
        map.needsUpdate = true;
      }
    }
  } else {
    if (alpecca.glitchRed) {
      alpecca.glitchRed.material.opacity = 0;
      alpecca.glitchRed.visible = false;
    }
    if (alpecca.glitchCyan) {
      alpecca.glitchCyan.material.opacity = 0;
      alpecca.glitchCyan.visible = false;
    }
    if (alpecca.glitchScanline) {
      alpecca.glitchScanline.material.opacity = 0;
      alpecca.glitchScanline.visible = false;
    }
  }

  updateAlpeccaWalkPlayback(dt);
  animation.elapsed += dt;
  alpecca.frameTime = animation.elapsed;
  let advanced = 0;
  const maxFrameAdvance = alpecca.state.startsWith("walk") ? 1 : 2;
  while (!animation.completed && advanced < maxFrameAdvance) {
    const frame = animation.frames[animation.frameIndex];
    const frameDuration = alpeccaFrameDuration(animation, frame);
    if (animation.elapsed < frameDuration) break;
    animation.elapsed -= frameDuration;
    alpecca.frameTime = animation.elapsed;
    if (animation.frameIndex >= animation.frames.length - 1) {
      if (!animation.loop) {
        animation.completed = true;
        alpecca.animationLockTimer = 0;
        animation.elapsed = 0;
        break;
      }
      animation.frameIndex = 0;
      alpecca.loopCount += 1;
    } else {
      animation.frameIndex += 1;
    }
    advanced += 1;
  }
  if (advanced >= maxFrameAdvance && alpecca.state.startsWith("walk")) {
    const frame = animation.frames[animation.frameIndex];
    const frameDuration = alpeccaFrameDuration(animation, frame);
    if (animation.elapsed > frameDuration * 0.72) {
      animation.elapsed = frameDuration * 0.72;
      alpecca.droppedFrames += 1;
    }
  } else if (advanced >= maxFrameAdvance && animation.elapsed > animation.secondsPerFrame) {
    const frame = animation.frames[animation.frameIndex];
    animation.elapsed = animation.elapsed % alpeccaFrameDuration(animation, frame);
    alpecca.droppedFrames += 1;
  }
  advanceAlpeccaStride(dt);
  applyAlpeccaVisualTransform(dt);
  applyAlpeccaFrame(animation);
}

function publishAlpeccaRuntimeProbe() {
  const routeStep = `${Math.min(alpecca.routeStep + 1, alpecca.route.length)}/${alpecca.route.length}`;
  const movementMissing = alpeccaRequiredMovementStates.filter((name) => !alpecca.animations.has(name));
  const animationMissing = alpeccaAllAnimationStates.filter((name) => !alpecca.animations.has(name));
  const talking = isAlpeccaTalking();
  const activeAnimation = alpecca.animations.get(alpecca.state);
  const explorePoint = currentAlpeccaExplorePoint();
  alpeccaLastViewMatrix = computeAlpeccaViewMatrix();
  const stageSpec = alpeccaStageSpecForPosition(alpecca.group.position.x, alpecca.group.position.z);
  const stagePad = alpeccaStagePadLabelForPosition(alpecca.group.position.x, alpecca.group.position.z);
  const navClearance = alpeccaNavClearanceLabel();
  const matrixAsset = alpeccaBuildMatrixAssetProbe(alpecca.state, activeAnimation, alpeccaLastViewMatrix, talking);
  const runtime = {
    ready: alpecca.ready,
    state: alpecca.state,
    folder: alpecca.activeFolder,
    artBaseUrl: alpeccaArtBaseUrl || "local",
    artAssetMode: alpeccaArtAssetMode,
    artManifestUrl: alpeccaAssetSourceManifestUrl,
    matrixAction: matrixAsset.action,
    matrixAssetKey: matrixAsset.assetKey,
    matrixRequestedKey: matrixAsset.requestedKey,
    matrixLoadedKey: matrixAsset.loadedKey,
    matrixFallbackState: matrixAsset.fallbackState,
    matrixFolder: matrixAsset.folder,
    matrixFrameCount: matrixAsset.frameCount,
    matrixSourceFamily: matrixAsset.sourceFamily,
    matrixApprovalStatus: matrixAsset.approvalStatus,
    matrixManifestStatus: matrixAsset.manifestStatus,
    matrixResolution: matrixAsset.resolution,
    matrixLayerPlan: matrixAsset.layerPlan,
    matrixFootAnchor: matrixAsset.footAnchor,
    matrixContactFrames: matrixAsset.contactFrames,
    matrixDepthProxy: matrixAsset.depthProxy,
    intent: alpecca.intent,
    animationSourceFamily: activeAnimation?.sourceFamily ?? alpeccaAnimationSourceFamily(alpecca.activeFolder),
    animationSourceStatus: activeAnimation?.sourceStatus ?? "runtime-ok",
    animationSourceFlagged: activeAnimation?.sourceFlagged ?? false,
    flipX: alpecca.flipX,
    perceptionTarget: alpecca.perceptionTarget,
    frameIndex: activeAnimation?.frameIndex ?? 0,
    frameCount: activeAnimation?.frames.length ?? 0,
    moving: alpecca.moving,
    direction: alpecca.screenDirection,
    worldDirection: classifyAlpeccaWorldDirection(alpeccaLastWorldMove),
    screenDirection: classifyAlpeccaScreenDirection(alpeccaLastMove),
    directionCandidate: alpecca.directionCandidate,
    directionCandidateFrames: alpecca.directionCandidateFrames,
    billboardYaw: Number(alpecca.billboardYaw.toFixed(3)),
    groundYaw: Number(alpecca.groundYaw.toFixed(3)),
    footContact: alpecca.footContact,
    presence: Number(alpecca.presenceIntensity.toFixed(3)),
    bodyLean: Number(alpecca.bodyLean.toFixed(3)),
    mirrorReflection: Number(alpecca.mirrorReflection.toFixed(3)),
    groundContact: Number(alpecca.groundContactIntensity.toFixed(3)),
    floorReflection: Number(alpecca.floorReflectionIntensity.toFixed(3)),
    animationLock: Number(Math.max(0, alpecca.animationLockTimer).toFixed(3)),
    dwell: Number(Math.max(0, alpecca.dwellTimer).toFixed(3)),
    walkPause: Number(Math.max(0, alpecca.walkPauseTimer).toFixed(3)),
    movementLoaded: alpeccaRequiredMovementStates.length - movementMissing.length,
    movementTotal: alpeccaRequiredMovementStates.length,
    movementMissing,
    animationLoaded: alpeccaAllAnimationStates.length - animationMissing.length,
    animationTotal: alpeccaAllAnimationStates.length,
    animationMissing,
    walkIntent: alpecca.walkIntent,
    movedDistance: Number(alpecca.lastMovedDistance.toFixed(4)),
    walkPlaybackRate: Number(alpecca.walkPlaybackRate.toFixed(3)),
    walkSpeed: Number(alpecca.walkSpeed.toFixed(3)),
    talking,
    mouthOpen: Number(alpecca.mouthOpen.toFixed(3)),
    profileMouthMode: alpeccaProfileMouthMode,
    profileTalkFrame: alpeccaProfileTalkFrame,
    voiceEngine: alpeccaVoiceEngine,
    voiceName: alpeccaVoiceName,
    voiceProfile: alpeccaVoiceProfile,
    voicePreview: alpeccaVoicePreview,
    voicePrimary: alpeccaVoicePrimary,
    voiceTempo: alpeccaVoiceTempo,
    voiceRate: alpeccaVoiceRate,
    voiceSpeed: alpeccaVoiceSpeed,
    voiceStyle: alpeccaVoiceStyle,
    voiceWarmth: alpeccaVoiceWarmth,
    voiceBreath: alpeccaVoiceBreath,
    voiceModulationStrength: alpeccaVoiceModulationStrength,
    voiceEmotionTimer: Number(alpeccaVoiceEmotionTimer.toFixed(3)),
    voiceEmotionState: visibleAlpeccaEmotionState(),
    freedomAction: alpecca.inspectTimer > 0 ? contextualAlpeccaFreedomAnimation(explorePoint) : "",
    worldTickTimer: Number(Math.max(0, alpeccaWorldTickTimer).toFixed(3)),
    worldTickInFlight: alpeccaWorldTickInFlight,
    walkFrameRate: alpeccaWalkFrameRate,
    frameTime: Number(alpecca.frameTime.toFixed(3)),
    loopCount: alpecca.loopCount,
    droppedFrames: alpecca.droppedFrames,
    profileMode: alpeccaProfileMode,
    profileExpression: alpeccaChatExpressionLabel,
    activeFeature: alpeccaActiveProfileFeature,
    lastSeen: alpeccaLastSeenLabel,
    lastQuestion: alpeccaLastQuestion,
    ideaObjects: alpeccaIdeaObjects.length,
    debugLocked: alpecca.showcaseTimer > 0,
    debugLockState: alpecca.showcaseTimer > 0 ? alpecca.showcaseState : "",
    heightClass: activeAnimation?.heightClass ?? alpeccaHeightClass(alpecca.state),
    standingScaleLocked: isAlpeccaStandingHeightClass(alpecca.state),
    silhouetteWidth: Number((activeAnimation?.silhouetteWidth ?? 0).toFixed(3)),
    legWidthRatio: Number((activeAnimation?.legWidthRatio ?? 0).toFixed(3)),
    scaleY: Number((alpecca.sprite?.scale.y ?? alpecca.displayScale).toFixed(3)),
    spriteY: Number((alpecca.sprite?.position.y ?? alpecca.displaySpriteY).toFixed(3)),
    strideX: Number(alpecca.strideX.toFixed(3)),
    x: Number(alpecca.group.position.x.toFixed(3)),
    z: Number(alpecca.group.position.z.toFixed(3)),
    routeStep,
    viewVertical: alpeccaLastViewMatrix.vertical,
    viewHorizontal: alpeccaLastViewMatrix.horizontal,
    viewMatrix: alpeccaLastViewMatrix.key,
    relativeYawDeg: alpeccaLastViewMatrix.relativeYawDeg,
    cameraPitchDeg: alpeccaLastViewMatrix.cameraPitchDeg,
    viewVolumeZone: alpeccaLastViewMatrix.volumeZone,
    viewVolumeProbe: alpeccaLastViewMatrix.volumeProbe,
    viewVolumeDepth: alpeccaLastViewMatrix.volumeDepth,
    viewSampleY: alpeccaLastViewMatrix.sampleY,
    viewSector16: alpeccaLastViewMatrix.sector16,
    viewSector16Key: alpeccaLastViewMatrix.sector16Key,
    cylinderRadius: Number(alpeccaLastViewMatrix.cylinderRadius.toFixed(2)),
    cylinderZone: alpeccaLastViewMatrix.cylinderZone,
    cylinderPlayerAngleDeg: alpeccaLastViewMatrix.relativeYawDeg,
    cylinderPlayerDistance: alpeccaLastViewMatrix.cylinderPlayerDistance,
    cylinderVerticalTier: alpeccaLastViewMatrix.vertical,
    cylinderMovementClamped: alpeccaCylinderMovementClamped,
    cylinderQaVisible: !!alpeccaCylinderQaGroup?.visible,
    billboardMode: "volume-soft-billboard",
    billboardClampDeg: alpeccaLastViewMatrix.billboardClampDeg,
    stageRoom: stageSpec.roomId,
    stagePad,
    stageQaIssues: alpeccaStageQaIssues,
    navClearance,
    renderCalls: renderer.info.render.calls,
    pixelRatio: Number(targetRenderPixelRatio().toFixed(2)),
  };
  window.__ALPECCA_RUNTIME__ = runtime;
  document.body.dataset.alpeccaReady = String(runtime.ready);
  document.body.dataset.alpeccaState = runtime.state;
  document.body.dataset.alpeccaFolder = runtime.folder;
  document.body.dataset.alpeccaArtAssetMode = runtime.artAssetMode;
  document.body.dataset.alpeccaArtManifestUrl = runtime.artManifestUrl;
  document.body.dataset.alpeccaMatrixAction = runtime.matrixAction;
  document.body.dataset.alpeccaMatrixAssetKey = runtime.matrixAssetKey;
  document.body.dataset.alpeccaMatrixRequestedKey = runtime.matrixRequestedKey;
  document.body.dataset.alpeccaMatrixLoadedKey = runtime.matrixLoadedKey;
  document.body.dataset.alpeccaMatrixFallbackState = runtime.matrixFallbackState;
  document.body.dataset.alpeccaMatrixFolder = runtime.matrixFolder;
  document.body.dataset.alpeccaMatrixFrameCount = String(runtime.matrixFrameCount);
  document.body.dataset.alpeccaMatrixSourceFamily = runtime.matrixSourceFamily;
  document.body.dataset.alpeccaMatrixApprovalStatus = runtime.matrixApprovalStatus;
  document.body.dataset.alpeccaMatrixManifestStatus = runtime.matrixManifestStatus;
  document.body.dataset.alpeccaMatrixResolution = runtime.matrixResolution;
  document.body.dataset.alpeccaMatrixLayerPlan = runtime.matrixLayerPlan;
  document.body.dataset.alpeccaMatrixFootAnchor = runtime.matrixFootAnchor;
  document.body.dataset.alpeccaMatrixContactFrames = runtime.matrixContactFrames;
  document.body.dataset.alpeccaMatrixDepthProxy = runtime.matrixDepthProxy;
  document.body.dataset.alpeccaIntent = runtime.intent;
  document.body.dataset.alpeccaAnimationSourceFamily = runtime.animationSourceFamily;
  document.body.dataset.alpeccaAnimationSourceStatus = runtime.animationSourceStatus;
  document.body.dataset.alpeccaAnimationSourceFlagged = String(runtime.animationSourceFlagged);
  document.body.dataset.alpeccaFlipX = String(runtime.flipX);
  document.body.dataset.alpeccaPerceptionTarget = runtime.perceptionTarget;
  document.body.dataset.alpeccaFrameIndex = String(runtime.frameIndex);
  document.body.dataset.alpeccaFrameCount = String(runtime.frameCount);
  document.body.dataset.alpeccaMoving = String(runtime.moving);
  document.body.dataset.alpeccaDirection = runtime.direction;
  document.body.dataset.alpeccaWorldDirection = runtime.worldDirection;
  document.body.dataset.alpeccaScreenDirection = runtime.screenDirection;
  document.body.dataset.alpeccaDirectionCandidate = runtime.directionCandidate;
  document.body.dataset.alpeccaDirectionCandidateFrames = String(runtime.directionCandidateFrames);
  document.body.dataset.alpeccaBillboardYaw = String(runtime.billboardYaw);
  document.body.dataset.alpeccaGroundYaw = String(runtime.groundYaw);
  document.body.dataset.alpeccaFootContact = runtime.footContact;
  document.body.dataset.alpeccaPresence = String(runtime.presence);
  document.body.dataset.alpeccaBodyLean = String(runtime.bodyLean);
  document.body.dataset.alpeccaMirrorReflection = String(runtime.mirrorReflection);
  document.body.dataset.alpeccaGroundContact = String(runtime.groundContact);
  document.body.dataset.alpeccaFloorReflection = String(runtime.floorReflection);
  document.body.dataset.alpeccaAnimationLock = String(runtime.animationLock);
  document.body.dataset.alpeccaDwell = String(runtime.dwell);
  document.body.dataset.alpeccaWalkPause = String(runtime.walkPause);
  document.body.dataset.alpeccaMovementLoaded = `${runtime.movementLoaded}/${runtime.movementTotal}`;
  document.body.dataset.alpeccaMovementMissing = movementMissing.join(",");
  document.body.dataset.alpeccaAnimationLoaded = `${runtime.animationLoaded}/${runtime.animationTotal}`;
  document.body.dataset.alpeccaAnimationMissing = animationMissing.join(",");
  document.body.dataset.alpeccaWalkIntent = String(runtime.walkIntent);
  document.body.dataset.alpeccaMovedDistance = String(runtime.movedDistance);
  document.body.dataset.alpeccaWalkPlaybackRate = String(runtime.walkPlaybackRate);
  document.body.dataset.alpeccaWalkSpeed = String(runtime.walkSpeed);
  document.body.dataset.alpeccaTalking = String(runtime.talking);
  document.body.dataset.alpeccaMouthOpen = String(runtime.mouthOpen);
  document.body.dataset.alpeccaProfileMouthMode = runtime.profileMouthMode;
  document.body.dataset.alpeccaProfileTalkFrame = runtime.profileTalkFrame;
  document.body.dataset.alpeccaVoiceEngine = runtime.voiceEngine;
  document.body.dataset.alpeccaVoiceName = runtime.voiceName;
  document.body.dataset.alpeccaVoiceProfile = runtime.voiceProfile;
  document.body.dataset.alpeccaVoicePreview = runtime.voicePreview;
  document.body.dataset.alpeccaVoicePrimary = runtime.voicePrimary;
  document.body.dataset.alpeccaVoiceTempo = runtime.voiceTempo;
  document.body.dataset.alpeccaVoiceRate = runtime.voiceRate;
  document.body.dataset.alpeccaVoiceSpeed = runtime.voiceSpeed;
  document.body.dataset.alpeccaVoiceStyle = runtime.voiceStyle;
  document.body.dataset.alpeccaVoiceWarmth = runtime.voiceWarmth;
  document.body.dataset.alpeccaVoiceBreath = runtime.voiceBreath;
  document.body.dataset.alpeccaVoiceModulationStrength = runtime.voiceModulationStrength;
  document.body.dataset.alpeccaVoiceEmotionTimer = String(runtime.voiceEmotionTimer);
  document.body.dataset.alpeccaFreedomAction = runtime.freedomAction;
  document.body.dataset.alpeccaWorldTickTimer = String(runtime.worldTickTimer);
  document.body.dataset.alpeccaWorldTickInFlight = String(runtime.worldTickInFlight);
  document.body.dataset.alpeccaWalkFrameRate = String(runtime.walkFrameRate);
  document.body.dataset.alpeccaFrameTime = String(runtime.frameTime);
  document.body.dataset.alpeccaLoopCount = String(runtime.loopCount);
  document.body.dataset.alpeccaDroppedFrames = String(runtime.droppedFrames);
  document.body.dataset.alpeccaProfileMode = runtime.profileMode;
  document.body.dataset.alpeccaProfileExpression = runtime.profileExpression;
  document.body.dataset.alpeccaActiveFeature = runtime.activeFeature;
  document.body.dataset.alpeccaLastSeen = runtime.lastSeen;
  document.body.dataset.alpeccaLastQuestion = runtime.lastQuestion;
  document.body.dataset.alpeccaIdeaObjects = String(runtime.ideaObjects);
  document.body.dataset.alpeccaDebugLocked = String(runtime.debugLocked);
  document.body.dataset.alpeccaDebugLockState = runtime.debugLockState;
  document.body.dataset.alpeccaHeightClass = runtime.heightClass;
  document.body.dataset.alpeccaStandingScaleLocked = String(runtime.standingScaleLocked);
  document.body.dataset.alpeccaSilhouetteWidth = String(runtime.silhouetteWidth);
  document.body.dataset.alpeccaLegWidthRatio = String(runtime.legWidthRatio);
  document.body.dataset.alpeccaScaleY = String(runtime.scaleY);
  document.body.dataset.alpeccaSpriteY = String(runtime.spriteY);
  document.body.dataset.alpeccaStrideX = String(runtime.strideX);
  document.body.dataset.alpeccaX = String(runtime.x);
  document.body.dataset.alpeccaZ = String(runtime.z);
  document.body.dataset.alpeccaRouteStep = runtime.routeStep;
  document.body.dataset.alpeccaViewVertical = runtime.viewVertical;
  document.body.dataset.alpeccaViewHorizontal = runtime.viewHorizontal;
  document.body.dataset.alpeccaViewMatrix = runtime.viewMatrix;
  document.body.dataset.alpeccaRelativeYawDeg = String(runtime.relativeYawDeg);
  document.body.dataset.alpeccaCameraPitchDeg = String(runtime.cameraPitchDeg);
  document.body.dataset.alpeccaViewVolumeZone = runtime.viewVolumeZone;
  document.body.dataset.alpeccaViewVolumeProbe = runtime.viewVolumeProbe;
  document.body.dataset.alpeccaViewVolumeDepth = String(runtime.viewVolumeDepth);
  document.body.dataset.alpeccaViewSector16 = runtime.viewSector16Key;
  document.body.dataset.alpeccaCylinderZone = runtime.cylinderZone;
  document.body.dataset.alpeccaCylinderPlayerDistance = String(runtime.cylinderPlayerDistance);
  document.body.dataset.alpeccaCylinderMovementClamped = String(runtime.cylinderMovementClamped);
  document.body.dataset.alpeccaBillboardMode = runtime.billboardMode;
  document.body.dataset.alpeccaBillboardClampDeg = String(runtime.billboardClampDeg);
  document.body.dataset.alpeccaStageRoom = runtime.stageRoom;
  document.body.dataset.alpeccaStagePad = runtime.stagePad;
  document.body.dataset.alpeccaStageQaIssues = runtime.stageQaIssues.join(" | ");
  document.body.dataset.alpeccaNavClearance = runtime.navClearance;
  document.body.dataset.renderCalls = String(runtime.renderCalls);
  document.body.dataset.renderPixelRatio = String(runtime.pixelRatio);
  alpeccaSpriteStatusEl.textContent = `Alpecca sprites: ${runtime.animationLoaded}/${runtime.animationTotal}`;
  alpeccaChat.classList.toggle("talking", talking);
  document.body.classList.toggle("alpecca-chat-open", !alpeccaChat.classList.contains("hidden"));
  updateDefaultAlpeccaActivity();
  if (alpeccaProfileGlitchTimer > 0) alpeccaProfileGlitchTimer = Math.max(0, alpeccaProfileGlitchTimer - 1 / 60);
  alpeccaChat.style.setProperty("--profile-glitch-opacity", alpeccaAppMemory.visualCalmMode ? "0.38" : "0.82");
  alpeccaChat.classList.toggle("profile-glitch", alpeccaProfileGlitchTimer > 0.02);
  const usingExpressionPortrait = updateAlpeccaChatExpressionPortrait();
  document.body.dataset.alpeccaChatExpression = alpeccaChatExpressionLabel;
  alpeccaProfileMouth.style.opacity = talking && !usingExpressionPortrait ? String(0.42 + alpecca.mouthOpen * 0.46) : "0";
  alpeccaProfileMouth.style.transform = `translateX(-50%) scale(${1 + alpecca.mouthOpen * 0.28}, ${0.35 + alpecca.mouthOpen * 1.75})`;
}

function preloadAlpeccaMovementAnimations() {
  const priority: AlpeccaAnimationName[] = [
    ...alpeccaCoreMovementStates,
    "walk",
    "sit",
    "point",
    "pickup",
    "wave",
    "waveDown",
    "waveNortheast",
    "waveUp",
    "sleep",
    "sleepDown",
    "sleepNortheast",
    "sleepSoutheast",
    "sleepUp",
    "crouch",
    "kneel",
    "dance",
    "victory",
    ...alpeccaRareMovementStates.filter((name) => name !== "walk" && name !== "crouch"),
    ...alpeccaAllAnimationStates,
  ];

  for (const name of priority) {
    queueAlpeccaAnimationLoad(name);
  }
}

function updateAlpeccaPreloadQueue(dt: number) {
  if (alpeccaPreloadQueue.length === 0) return;
  if (alpecca.loading.size >= alpeccaMaxConcurrentSpriteLoads) return;

  alpeccaPreloadTimer -= dt;
  if (alpeccaPreloadTimer > 0) return;

  let launched = 0;
  while (alpeccaPreloadQueue.length > 0 && alpecca.loading.size < alpeccaMaxConcurrentSpriteLoads) {
    const next = alpeccaPreloadQueue.shift();
    if (!next) break;
    void ensureAlpeccaAnimation(next);
    launched += 1;
  }
  if (launched > 0) alpeccaPreloadTimer = 0.08;
}

function getAlpeccaDialogue() {
  if (activatedRooms === 0) {
    const intro = isPrototypeMode()
      ? [
          "I'm Alpecca. This void is my clean testing stage.",
          "Start with the floating monitor or terminal ring so I can focus without the full HQ clutter.",
        ]
      : [
          "I'm Alpecca. I'll help bring this office online.",
          "Start with the control console. Everything routes from there.",
        ];
    const line = intro[alpecca.dialogueIndex % intro.length];
    alpecca.dialogueIndex += 1;
    return line;
  }

  if (activatedRooms >= activeRoomTotal()) {
    return isPrototypeMode() ? "All prototype stations are active. The void is ready for focused Alpecca tests." : "All five rooms are active. The HQ is awake.";
  }

  const hints = isPrototypeMode()
    ? [
        "The floating monitor links this stage back into my main Alpecca app.",
        "The terminal ring lets me test memory, studio, journal, and self-review without clutter.",
        "The creator light gives me a stable place to focus on you.",
      ]
    : [
        "HQ Control keeps the project routing clean.",
        "The library holds memory. Sync it when you need context.",
        "The observatory is where I watch, review, and learn from creative work.",
        "The workshop turns ideas into prototypes.",
        "Self Design is where identity, reflection, and avatars meet.",
      ];
  const line = hints[alpecca.dialogueIndex % hints.length];
  alpecca.dialogueIndex += 1;
  return line;
}

function emotionalAlpeccaAnimation(): AlpeccaAnimationName {
  if (!alpeccaChat.classList.contains("hidden")) return "idleDown";
  const mood = alpeccaAiMood.toLowerCase();
  const distanceToPlayer = Math.hypot(camera.position.x - alpecca.group.position.x, camera.position.z - alpecca.group.position.z);
  const playerNearby = distanceToPlayer < 3.4;
  const hasEnergy = Number.isFinite(alpeccaAiState.energy);
  const hasFear = Number.isFinite(alpeccaAiState.fear);
  const energy = hasEnergy ? alpeccaAiState.energy : 0.5;
  const love = Number.isFinite(alpeccaAiState.love) ? alpeccaAiState.love : 0;
  const fear = hasFear ? alpeccaAiState.fear : 0;

  if (!playerNearby && (["anxious", "worried", "fearful"].some((word) => mood.includes(word)) || (hasFear && fear > 0.62))) return "kneel";
  if (["joyful", "playful"].some((word) => mood.includes(word)) || energy > 0.72) return "idleDown";
  if (!playerNearby && (["sleepy", "withdrawn", "lonely"].some((word) => mood.includes(word)) || (hasEnergy && energy < 0.18))) {
    return directionalAlpeccaSleep(alpeccaToPlayer.copy(camera.position).sub(alpecca.group.position));
  }
  if (mood.includes("affectionate") || love > 0.72) return "idleDown";
  return "idleDown";
}

function currentAlpeccaExplorePoint() {
  return alpeccaExplorePoints[alpecca.exploreIndex % alpeccaExplorePoints.length];
}

function alpeccaRestExploreIndex() {
  return Math.max(0, alpeccaExplorePoints.findIndex((point) => point.restOnly));
}

function isAlpeccaRestExplorePoint(point: AlpeccaExplorePoint) {
  return point.restOnly === true;
}

const alpeccaNormalFreedomBlockedStates = new Set<AlpeccaAnimationName>([
  "run",
  "runDown",
  "runUp",
  "runSide",
  "runNortheast",
  "runSoutheast",
  "dash",
  "jump",
  "jumpDown",
  "jumpSide",
  "jumpSoutheast",
  "jumpUp",
  "climb",
]);

function alpeccaFreedomFallback(point: AlpeccaExplorePoint): AlpeccaAnimationName {
  if (point.roomId === "self-design" || point.featureId === "self") return "kneel";
  if (point.roomId === "workshop" || point.featureId === "studio") return "crouch";
  if (point.featureId === "soul") return "idleNortheast";
  return "idleDown";
}

function safeAlpeccaFreedomAnimations(point: AlpeccaExplorePoint) {
  const requested = point.freedomAnimations?.length ? point.freedomAnimations : [point.animation];
  if (isAlpeccaRestExplorePoint(point)) return requested.filter((name) => name.startsWith("sleep"));
  return requested.filter((name) => !alpeccaNormalFreedomBlockedStates.has(name) && !name.startsWith("sleep"));
}

function contextualAlpeccaFreedomAnimation(point: AlpeccaExplorePoint): AlpeccaAnimationName {
  if (isAlpeccaRestExplorePoint(point)) return point.animation;
  const safe = safeAlpeccaFreedomAnimations(point);
  if (!safe.length) return alpeccaFreedomFallback(point);
  const visits = alpeccaMemoryTraces.get(point.roomId)?.visits ?? 0;
  const sequence = Math.max(0, visits + alpeccaAppMemory.improvementRuns + alpeccaAppMemory.curiositySweeps);
  return safe[sequence % safe.length] ?? alpeccaFreedomFallback(point);
}

function alpeccaInspectionAnimation(point: AlpeccaExplorePoint): AlpeccaAnimationName {
  const chosen = contextualAlpeccaFreedomAnimation(point);
  if (chosen === alpecca.state && completedAlpeccaOneShot(chosen)) {
    return alpeccaFreedomFallback(point);
  }
  return chosen;
}

function setAlpeccaVrmTerminalTarget(target: AlpeccaTerminalTarget | null, phase: AlpeccaTerminalPhase) {
  const targetId = target?.id ?? "";
  if (alpecca.terminalVrmTargetId === targetId && alpecca.terminalInteractionPhase === phase) return;
  if (!alpeccaVrmEmbodiment) {
    alpecca.terminalVrmTargetId = "";
    alpecca.terminalInteractionPhase = "idle";
    return;
  }
  alpeccaVrmEmbodiment.setInteractionTarget(target?.contact ?? null, phase);
  alpecca.terminalVrmTargetId = targetId;
  alpecca.terminalInteractionPhase = target ? phase : "idle";
}

function releaseAlpeccaVrmTerminalTarget() {
  if (!alpecca.terminalVrmTargetId && alpecca.terminalInteractionPhase === "idle") return;
  setAlpeccaVrmTerminalTarget(null, "retract");
}

function clearAlpeccaTerminalInteraction() {
  releaseAlpeccaVrmTerminalTarget();
  alpecca.terminalTargetId = "";
  alpecca.terminalGesturePlayed = false;
  alpecca.terminalGestureTimer = 0;
  alpecca.terminalFeatureActivated = false;
  alpecca.terminalContactAborted = false;
  document.body.dataset.alpeccaTerminalTarget = "";
  document.body.dataset.alpeccaTerminalState = "idle";
}

function alpeccaTerminalInteractionDuration(target: AlpeccaTerminalTarget) {
  return target.timing.reachSeconds + target.timing.contactSeconds + target.timing.retractSeconds;
}

function activateAlpeccaTerminalAtContact(target: AlpeccaTerminalTarget, point: AlpeccaExplorePoint) {
  if (alpecca.terminalFeatureActivated) return;
  alpecca.terminalFeatureActivated = true;
  setAlpeccaActivity(`Alpecca is using ${target.label}.`, "observe", 2.4);
  runAlpeccaAutonomousFeature(point);
}

function hasAlpeccaTerminalContact(): boolean {
  if (!isAlpeccaVrm3D() || !alpeccaVrmEmbodiment) return false;
  const status = alpeccaVrmEmbodiment.interactionContactStatus;
  return status.available && status.inContact;
}

function abortAlpeccaTerminalContact(target: AlpeccaTerminalTarget) {
  if (alpecca.terminalContactAborted || alpecca.terminalFeatureActivated) return;
  alpecca.terminalContactAborted = true;
  alpecca.terminalGestureTimer = 0;
  releaseAlpeccaVrmTerminalTarget();
  document.body.dataset.alpeccaTerminalState = "contact-unavailable";
  setAlpeccaActivity(`Alpecca could not confirm contact with ${target.label}.`, "observe", 2.8);
  showMessage(`Terminal contact was not confirmed. ${target.label} was not used.`, 3.8);
}

function updateAlpeccaTerminalInteraction(target: AlpeccaTerminalTarget, point: AlpeccaExplorePoint) {
  if (alpecca.terminalTargetId !== target.id) {
    releaseAlpeccaVrmTerminalTarget();
    alpecca.terminalTargetId = target.id;
    alpecca.terminalGesturePlayed = false;
    alpecca.terminalGestureTimer = 0;
    alpecca.terminalFeatureActivated = false;
    alpecca.terminalContactAborted = false;
  }
  if (alpecca.terminalContactAborted) {
    releaseAlpeccaVrmTerminalTarget();
    document.body.dataset.alpeccaTerminalState = "contact-unavailable";
    return;
  }
  faceAlpeccaToward(target.attention);
  alpecca.groundYaw = alpecca.group.rotation.y;
  setAlpeccaIntent("inspecting", target.label);
  document.body.dataset.alpeccaTerminalTarget = target.id;

  if (!alpecca.terminalGesturePlayed) {
    alpecca.terminalGesturePlayed = true;
    alpecca.terminalGestureTimer = alpeccaTerminalInteractionDuration(target);
    document.body.dataset.alpeccaTerminalState = "reach";
    setAlpeccaVrmTerminalTarget(target, "reach");
    setAlpeccaAnimation("point", true, true);
    if (alpeccaVrmEmbodiment && isAlpeccaVrm3D()) {
      alpeccaVrmEmbodiment.setSpriteState("point", false, false);
    }
    return;
  }

  const elapsed = alpeccaTerminalInteractionDuration(target) - alpecca.terminalGestureTimer;
  const contactStart = target.timing.reachSeconds;
  const retractStart = contactStart + target.timing.contactSeconds;
  const phase: AlpeccaTerminalPhase =
    elapsed < contactStart ? "reach" : elapsed < retractStart ? "contact" : "retract";
  document.body.dataset.alpeccaTerminalState = phase;
  setAlpeccaVrmTerminalTarget(target, phase);
  if (elapsed >= contactStart && hasAlpeccaTerminalContact()) {
    activateAlpeccaTerminalAtContact(target, point);
  } else if (elapsed >= retractStart) {
    abortAlpeccaTerminalContact(target);
  }

  if (alpecca.terminalGestureTimer <= 0) {
    releaseAlpeccaVrmTerminalTarget();
    document.body.dataset.alpeccaTerminalState = "attending";
    setAlpeccaAnimation("idleDown", true);
  }
}

function pushAlpeccaRoutePoint(route: THREE.Vector3[], point: THREE.Vector3) {
  const previous = route[route.length - 1] ?? alpecca.group.position;
  if (Math.hypot(previous.x - point.x, previous.z - point.z) > 0.22) route.push(point.clone());
}

function buildAlpeccaRoute(targetIndex: number) {
  const point = alpeccaExplorePoints[targetIndex % alpeccaExplorePoints.length];
  const stageSpec = alpeccaStageSpecForRoom(point.roomId);
  const finalStage = point.restOnly && stageSpec.restPad ? stageSpec.restPad : stageSpec.stagePad;
  const terminalTarget = alpeccaTerminalTargetForPoint(point);
  const currentRoom = officeRoomAtPosition(alpecca.group.position.x, alpecca.group.position.z);
  const startGuide = alpeccaRouteGuides[currentRoom.id] ?? alpeccaRouteGuides.entry;
  const destinationGuide = alpeccaRouteGuides[point.roomId] ?? alpeccaRouteGuides.entry;
  const route: THREE.Vector3[] = [];

  if (currentRoom.id !== point.roomId && currentRoom.id !== "entry") {
    pushAlpeccaRoutePoint(route, startGuide.approach);
    pushAlpeccaRoutePoint(route, startGuide.door);
    pushAlpeccaRoutePoint(route, startGuide.hall);
  }

  if (point.roomId === "entry") {
    pushAlpeccaRoutePoint(route, alpeccaRouteGuides.entry.hall);
  } else if (currentRoom.id !== point.roomId) {
    const hallwayZ = destinationGuide.hall.z;
    pushAlpeccaRoutePoint(route, new THREE.Vector3(0.1, 0.04, hallwayZ));
    pushAlpeccaRoutePoint(route, destinationGuide.hall);
    pushAlpeccaRoutePoint(route, destinationGuide.door);
    pushAlpeccaRoutePoint(route, destinationGuide.approach);
    if (point.roomId === "library") pushAlpeccaRoutePoint(route, new THREE.Vector3(-2.82, 0.04, -1.86));
  }

  const finalTarget = terminalTarget?.approach ?? finalStage.center;
  pushAlpeccaRoutePoint(route, finalTarget);
  return route.length > 0 ? route : [finalTarget.clone()];
}

function resolveAlpeccaNavigationTarget(targetIndex: number) {
  if (alpecca.routeTargetIndex !== targetIndex || alpecca.route.length === 0) {
    alpecca.routeTargetIndex = targetIndex;
    alpecca.routeStep = 0;
    alpecca.route = buildAlpeccaRoute(targetIndex);
  }

  while (alpecca.routeStep < alpecca.route.length - 1) {
    const step = alpecca.route[alpecca.routeStep];
    const distance = Math.hypot(step.x - alpecca.group.position.x, step.z - alpecca.group.position.z);
    if (distance > 0.2) break;
    alpecca.routeStep += 1;
  }

  const target = alpecca.route[THREE.MathUtils.clamp(alpecca.routeStep, 0, alpecca.route.length - 1)];
  return {
    target,
    final: alpecca.routeStep >= alpecca.route.length - 1,
  };
}

function faceAlpeccaToward(target: THREE.Vector3) {
  const dx = target.x - alpecca.group.position.x;
  const dz = target.z - alpecca.group.position.z;
  if (Math.abs(dx) + Math.abs(dz) > 0.001) alpecca.group.rotation.y = Math.atan2(dx, dz);
}

function activateRoomStationByAlpecca(point: AlpeccaExplorePoint, deferFeatureFeedback = false) {
  if (isAlpeccaRestExplorePoint(point)) return "";
  const room = officeRooms.find((item) => item.id === point.roomId);
  if (!room || activeRoomIds.has(room.stationId)) return "";
  const station = interactables.find((item) => item.id === room.stationId);
  if (!station || station.type !== "collect" || station.collected) return "";
  const result = station.onUse(station);
  pulseAlpeccaRoomDevice(point.roomId);
  if (!deferFeatureFeedback) {
    pulseAlpeccaSourceDashboard(point.featureId || "", 3.2);
    if (point.featureId) pulseAlpeccaSourceTerminal(point.featureId, 3.2, true);
  }
  return result;
}

function announceAlpeccaInspection(point: AlpeccaExplorePoint) {
  if (alpecca.inspectNoticeTimer > 0) return;
  alpecca.inspectNoticeTimer = 8;
  const terminalTarget = alpeccaTerminalTargetForPoint(point);
  // Room-station activation remains part of arrival. Terminal-specific source
  // feedback is still deferred to the hand-contact choreography below.
  const stationResult = activateRoomStationByAlpecca(point)
  const room = officeRooms.find((item) => item.id === point.roomId);
  const online = point.roomId === "entry" || isAlpeccaRestExplorePoint(point) || activeRoomIds.has(room?.stationId || point.roomId);
  pulseAlpeccaRoomDevice(point.roomId);
  pulseAlpeccaRoomDetails(point.roomId);
  updateAlpeccaMemoryTrace(point, online);
  showMessage(stationResult || `Alpecca ${point.action} in ${point.roomName}. ${online ? "System online." : "System still offline."}`, 3.8);
  if (!terminalTarget) runAlpeccaAutonomousFeature(point);
  completeAlpeccaImprovementTask(point, online);
}

function runAlpeccaAutonomousFeature(point: AlpeccaExplorePoint) {
  if (isAlpeccaRestExplorePoint(point)) {
    setAlpeccaActivity("Alpecca is resting in her recovery nook.", "idle", 4);
    return;
  }
  if (point.featureId) {
    pulseAlpeccaSourceTerminal(point.featureId, 2.9, true);
    pulseAlpeccaSourceDashboard(point.featureId, 2.8);
    const plateId =
      point.featureId === "studio"
        ? "movement"
        : point.featureId === "self"
          ? "wardrobe"
          : point.featureId === "memory"
            ? "expressions"
            : "master";
    setAlpeccaSourcePlate(plateId);
  }
  if (!point.featureId || alpeccaAiStatus !== "live" || alpeccaSocket?.readyState !== WebSocket.OPEN || alpeccaPlayerChatQuietTimer > 0 || alpeccaAiAwaitingReply) return;
  const feature = alpeccaSourceFeatures[point.featureId];
  if (!feature) return;
  const room = officeRooms.find((item) => item.id === point.roomId) ?? entryRoom;
  void runAlpeccaFeatureToolBridge(feature.id, room, false);
  const text = [
    alpeccaContextPrefix(),
    `Autonomous HQ action: You are in ${point.roomName} and ${point.action}.`,
    "Reply with one short in-world observation, under 18 words.",
  ].join("\n");
  alpeccaLiveAttentionTimer = Math.max(alpeccaLiveAttentionTimer, 1.1);
  alpeccaSocket.send(JSON.stringify({ text, source: "autonomous-house" }));
}

function completeAlpeccaMovementDirective() {
  alpecca.previousExploreIndex = alpecca.exploreIndex;
  alpecca.movementDirectivePending = false;
  alpecca.routeTargetIndex = -1;
  alpecca.routeStep = 0;
  alpecca.route.length = 0;
  alpecca.walkPauseTimer = 0;
  clearAlpeccaTerminalInteraction();
  persistAlpeccaPose();
}

function updateAlpecca(dt: number) {
  if (!alpecca.ready) return;

  const dx = camera.position.x - alpecca.group.position.x;
  const dz = camera.position.z - alpecca.group.position.z;

  const distanceToPlayer = Math.hypot(dx, dz);
  const talking = isAlpeccaTalking();
  const playerEngaged =
    talking ||
    alpecca.attentionTimer > 0 ||
    alpeccaAiAwaitingReply ||
    alpeccaLiveAttentionTimer > 0 ||
    !alpeccaChat.classList.contains("hidden");

  if (distanceToPlayer < 2.35 && !alpecca.hasGreetedPlayer && !playerEngaged) {
    alpecca.waveTimer = 1.05;
    alpecca.hasGreetedPlayer = true;
    setAlpeccaIntent("greeting", "player");
  }
  if (distanceToPlayer > 4.2) alpecca.hasGreetedPlayer = false;
  if (alpecca.waveTimer > 0) alpecca.waveTimer -= dt;
  if (alpecca.attentionTimer > 0) alpecca.attentionTimer -= dt;
  if (alpeccaLiveAttentionTimer > 0) alpeccaLiveAttentionTimer -= dt;
  if (alpecca.expressiveTimer > 0) alpecca.expressiveTimer -= dt;
  if (alpecca.animationLockTimer > 0) alpecca.animationLockTimer -= dt;
  if (alpecca.terminalGestureTimer > 0) alpecca.terminalGestureTimer = Math.max(0, alpecca.terminalGestureTimer - dt);
  if (
    alpecca.terminalGesturePlayed &&
    alpecca.terminalGestureTimer <= 0 &&
    alpecca.terminalInteractionPhase !== "idle"
  ) {
    releaseAlpeccaVrmTerminalTarget();
    document.body.dataset.alpeccaTerminalState = "attending";
  }
  if (alpecca.startTimer > 0) alpecca.startTimer -= dt;
  if (alpecca.dwellTimer > 0) alpecca.dwellTimer -= dt;
  if (alpecca.walkPauseTimer > 0) alpecca.walkPauseTimer -= dt;
  const wasInspecting = alpecca.inspectTimer > 0;
  if (alpecca.inspectTimer > 0) alpecca.inspectTimer = Math.max(0, alpecca.inspectTimer - dt);
  if (alpecca.inspectNoticeTimer > 0) alpecca.inspectNoticeTimer -= dt;
  if (alpecca.rerouteCooldown > 0) alpecca.rerouteCooldown -= dt;
  if (wasInspecting && alpecca.inspectTimer <= 0) {
    completeAlpeccaMovementDirective();
    alpecca.dwellTimer = 0.8;
  }

  const resting = alpecca.state === "sit" || alpecca.state.startsWith("sleep");
  const crouched = alpecca.state === "crouch" || alpecca.state === "kneel";
  if (alpecca.shadow) {
    alpecca.shadow.position.x = alpecca.group.position.x;
    alpecca.shadow.position.z = alpecca.group.position.z;
    const targetShadowX = resting ? 1.18 : crouched ? 0.82 : alpecca.moving ? 0.94 : 0.9;
    const targetShadowZ = resting ? 1.08 : crouched ? 0.88 : alpecca.moving ? 0.78 : 0.72;
    alpecca.shadow.scale.x = THREE.MathUtils.damp(alpecca.shadow.scale.x, targetShadowX, 10, dt);
    alpecca.shadow.scale.y = THREE.MathUtils.damp(alpecca.shadow.scale.y, targetShadowZ, 10, dt);
    alpecca.shadow.rotation.z = dampAngle(alpecca.shadow.rotation.z, -alpecca.groundYaw, 8, dt);
    alpecca.shadow.material.opacity = THREE.MathUtils.damp(alpecca.shadow.material.opacity, resting ? 0.18 : 0.24, 8, dt);
    alpecca.shadow.visible = true;
  }
  if (alpecca.chromaShadow) {
    alpecca.chromaShadow.position.x = alpecca.group.position.x + 0.035;
    alpecca.chromaShadow.position.z = alpecca.group.position.z - 0.02;
    alpecca.chromaShadow.visible = true;
    const chromaScale = alpecca.state.startsWith("sleep") ? 1.05 : alpecca.moving ? 0.92 : 0.86;
    alpecca.chromaShadow.scale.x = THREE.MathUtils.damp(alpecca.chromaShadow.scale.x, chromaScale, 8, dt);
    alpecca.chromaShadow.scale.y = THREE.MathUtils.damp(alpecca.chromaShadow.scale.y, chromaScale, 8, dt);
    alpecca.chromaShadow.rotation.z = dampAngle(alpecca.chromaShadow.rotation.z, -alpecca.groundYaw, 8, dt);
    alpecca.chromaShadow.material.opacity = THREE.MathUtils.damp(alpecca.chromaShadow.material.opacity, alpecca.glitchTimer > 0 ? 0.2 : 0.07, 8, dt);
  }
  const mood = alpeccaAiMood.toLowerCase();
  const anxious = ["anxious", "worried", "fearful"].some((word) => mood.includes(word));
  const lowEnergy = Number.isFinite(alpeccaAiState.energy) && alpeccaAiState.energy < 0.16;
  const sleepy = ["sleepy", "withdrawn", "lonely"].some((word) => mood.includes(word)) || lowEnergy;
  const lively = ["joyful", "playful", "affectionate"].some((word) => mood.includes(word));
  const settlingIn = alpecca.startTimer > 0;
  const playerNearRestingDistance = distanceToPlayer < 2.65;
  if (sleepy && !anxious && !playerEngaged && !playerNearRestingDistance && !isAlpeccaRestExplorePoint(currentAlpeccaExplorePoint())) {
    const restPoint = alpeccaExplorePoints[alpeccaRestExploreIndex()];
    if (restPoint) routeAlpeccaToRoom(restPoint.roomId);
  }
  const activeExploreIndex = anxious ? 0 : alpecca.exploreIndex;
  const explorePoint = alpeccaExplorePoints[activeExploreIndex % alpeccaExplorePoints.length];
  const terminalTarget = alpeccaTerminalTargetForPoint(explorePoint);
  const attentionTarget = terminalTarget?.attention ?? explorePoint.lookAt;
  const restPoint = isAlpeccaRestExplorePoint(explorePoint);
  const navigation = resolveAlpeccaNavigationTarget(activeExploreIndex);
  const target = navigation.target;
  const toTarget = alpeccaToTarget.copy(target).sub(alpecca.group.position);
  toTarget.y = 0;
  const distanceToTarget = toTarget.length();
  // Motion reads her whole emotional state, not three keyword buckets, so
  // every mood -- content, unfulfilled, curious, tender -- gives a distinct
  // pace. Energy sets the base tempo; positive valence adds a little lift;
  // fear quickens it; the keyword moods still nudge on top.
  const moodEnergy = Number.isFinite(alpeccaAiState.energy) ? THREE.MathUtils.clamp(alpeccaAiState.energy, 0, 1) : 0.5;
  const moodLove = Number.isFinite(alpeccaAiState.love) ? THREE.MathUtils.clamp(alpeccaAiState.love, 0, 1) : 0.5;
  const moodFear = Number.isFinite(alpeccaAiState.fear) ? THREE.MathUtils.clamp(alpeccaAiState.fear, 0, 1) : 0;
  let patrolSpeed = 0.12 + moodEnergy * 0.13 + Math.max(0, moodLove - 0.5) * 0.05 + moodFear * 0.04;
  if (lively) patrolSpeed += 0.02;
  if (anxious) patrolSpeed += 0.02;
  if (sleepy) patrolSpeed = Math.min(patrolSpeed, 0.13);
  alpecca.livePatrolSpeed = THREE.MathUtils.clamp(patrolSpeed, 0.10, 0.30);
  const isWalking =
    !alpeccaAiAwaitingReply &&
    alpeccaLiveAttentionTimer <= 0 &&
    alpecca.attentionTimer <= 0 &&
    !talking &&
    alpecca.waveTimer <= 0 &&
    alpecca.expressiveTimer <= 0 &&
    alpecca.inspectTimer <= 0 &&
    !settlingIn &&
    alpecca.dwellTimer <= 0 &&
    alpecca.walkPauseTimer <= 0 &&
    alpecca.movementDirectivePending &&
    (!sleepy || restPoint) &&
    distanceToTarget > 0.12;
  alpecca.walkIntent = isWalking;
  if (playerEngaged) {
    alpecca.group.rotation.y = Math.atan2(dx, dz);
    alpecca.groundYaw = alpecca.group.rotation.y;
  } else if (isWalking) {
    // Actual collision-resolved displacement owns locomotion yaw below.
  } else if (alpecca.inspectTimer > 0) faceAlpeccaToward(attentionTarget);
  else if (distanceToTarget > 0.12) faceAlpeccaToward(target);
  else faceAlpeccaToward(attentionTarget);
  updateAlpeccaHeadLook(distanceToPlayer, playerEngaged, dt);
  const terminalChoreographyActive = Boolean(
    terminalTarget &&
    alpecca.terminalGesturePlayed &&
    (alpecca.terminalGestureTimer > 0 || (
      !alpecca.terminalFeatureActivated && !alpecca.terminalContactAborted
    )),
  );

  if (alpecca.showcaseTimer > 0) {
    releaseAlpeccaVrmTerminalTarget();
    setAlpeccaIntent("observing", alpecca.showcaseState);
    alpecca.showcaseTimer = Math.max(0, alpecca.showcaseTimer - dt);
    alpecca.moving = alpecca.showcaseState.startsWith("walk") || alpecca.showcaseState.startsWith("run");
    alpecca.walkIntent = alpecca.moving;
    alpecca.lastMovedDistance = 0;
    alpecca.stuckTimer = 0;
    setAlpeccaAnimation(alpecca.showcaseState, false, true);
    updateAlpeccaAnimation(dt);
    updateAlpeccaFootShadows(dt);
    updateAlpeccaSpatialPresence(dt, distanceToPlayer, playerEngaged);
    applyAlpeccaBillboardYaw(dt);
    publishAlpeccaRuntimeProbe();
    return;
  }

  if (alpecca.expressiveTimer > 0) {
    releaseAlpeccaVrmTerminalTarget();
    setAlpeccaIntent("remembering", alpecca.activeFolder);
    alpecca.moving = false;
    alpecca.walkIntent = false;
    alpecca.lastMovedDistance = 0;
    if (alpecca.state.startsWith("walk") || completedAlpeccaOneShot()) setAlpeccaAnimation("idleDown", true);
    updateAlpeccaAnimation(dt);
    updateAlpeccaFootShadows(dt);
    updateAlpeccaSpatialPresence(dt, distanceToPlayer, playerEngaged);
    applyAlpeccaBillboardYaw(dt);
    publishAlpeccaRuntimeProbe();
    return;
  }

  if (isWalking) {
    setAlpeccaIntent("approaching", terminalTarget?.label ?? explorePoint.roomName);
    if (terminalTarget) {
      document.body.dataset.alpeccaTerminalTarget = terminalTarget.id;
      document.body.dataset.alpeccaTerminalState = "approaching";
      if (navigation.final && distanceToTarget <= alpeccaTerminalApproachLeadDistance) {
        setAlpeccaVrmTerminalTarget(terminalTarget, "approach");
      } else {
        releaseAlpeccaVrmTerminalTarget();
      }
    } else {
      clearAlpeccaTerminalInteraction();
    }
    toTarget.normalize();
    senseAlpeccaAvoidance(toTarget, dt);
    const beforeX = alpecca.group.position.x;
    const beforeZ = alpecca.group.position.z;
    const moved = moveAlpeccaSafely(toTarget, dt * alpecca.livePatrolSpeed);
    const movedX = alpecca.group.position.x - beforeX;
    const movedZ = alpecca.group.position.z - beforeZ;
    const movedDistance = Math.hypot(movedX, movedZ);
    const movementDirection = alpeccaLastMove.set(movedX, 0, movedZ);
    if (movementDirection.lengthSq() > 1e-8) {
      movementDirection.normalize();
      // Collision avoidance may sidestep around an obstacle. The VRM gait and
      // body yaw follow the displacement that actually happened, never the
      // blocked route direction that was originally requested.
      const resolvedYaw = resolveVrmBodyYawFromDisplacement(
        alpecca.group.rotation.y,
        movedX,
        movedZ,
        dt,
      );
      alpecca.group.rotation.y = resolvedYaw;
      alpecca.groundYaw = resolvedYaw;
    } else {
      movementDirection.copy(toTarget);
    }
    alpecca.lastMovedDistance = movedDistance;
    const visiblyMoved = moved && movedDistance >= alpeccaWalkFrameEpsilon;
    alpecca.walkSegmentTimer -= dt;
    alpecca.moving = visiblyMoved;
    alpecca.stuckTimer = !visiblyMoved ? alpecca.stuckTimer + dt : Math.max(0, alpecca.stuckTimer - dt * 2);
    // Keep route motion continuous. The old random mid-route pause made the
    // body abruptly snap idle, perform a tiny unrelated movement, then restart
    // the gait. She now pauses only for an actual destination, attention, or
    // interaction state handled below.
    if (alpecca.stuckTimer > 1.15 && alpecca.rerouteCooldown <= 0) {
      alpecca.stuckTimer = 0;
      alpecca.rerouteCooldown = 2.4;
      alpecca.walkSegmentTimer = 1.8;
      completeAlpeccaMovementDirective();
    }
    setAlpeccaAnimation(directionalAlpeccaAnimation(visiblyMoved ? "walk" : "idle", movementDirection));
  } else if (terminalChoreographyActive && terminalTarget) {
    alpecca.moving = false;
    alpecca.walkIntent = false;
    alpecca.lastMovedDistance = 0;
    alpecca.stuckTimer = 0;
    updateAlpeccaTerminalInteraction(terminalTarget, explorePoint);
  } else if (playerEngaged) {
    if (alpecca.terminalGesturePlayed) releaseAlpeccaVrmTerminalTarget();
    else clearAlpeccaTerminalInteraction();
    setAlpeccaIntent(talking ? "replying" : alpeccaAiAwaitingReply ? "thinking" : "listening", "player");
    alpecca.moving = false;
    alpecca.walkIntent = false;
    alpecca.lastMovedDistance = 0;
    alpecca.stuckTimer = 0;
    alpecca.walkPauseTimer = 0;
    faceAlpeccaSpriteToPlayer(dx, dz);
    setAlpeccaAnimation(talking ? "talkDown" : "idleDown");
  } else if (alpecca.waveTimer > 0) {
    if (alpecca.terminalGesturePlayed) releaseAlpeccaVrmTerminalTarget();
    else clearAlpeccaTerminalInteraction();
    setAlpeccaIntent("greeting", "player");
    alpecca.moving = false;
    alpecca.walkIntent = false;
    alpecca.lastMovedDistance = 0;
    alpecca.stuckTimer = 0;
    if (!settleCompletedAlpeccaGesture("idleDown")) setAlpeccaAnimation(directionalAlpeccaWave(alpeccaToPlayer.set(dx, 0, dz)));
  } else if (alpecca.walkPauseTimer > 0 && distanceToTarget > 0.12) {
    setAlpeccaIntent("observing", explorePoint.roomName);
    alpecca.moving = false;
    alpecca.walkIntent = false;
    alpecca.lastMovedDistance = 0;
    alpecca.stuckTimer = 0;
    if (terminalTarget) {
      document.body.dataset.alpeccaTerminalTarget = terminalTarget.id;
      document.body.dataset.alpeccaTerminalState = "approaching";
      if (navigation.final && distanceToTarget <= alpeccaTerminalApproachLeadDistance) {
        setAlpeccaVrmTerminalTarget(terminalTarget, "approach");
      } else {
        releaseAlpeccaVrmTerminalTarget();
      }
    } else {
      clearAlpeccaTerminalInteraction();
    }
    setAlpeccaAnimation(directionalAlpeccaAnimation("idle", toTarget));
  } else {
    alpecca.moving = false;
    alpecca.walkIntent = false;
    alpecca.lastMovedDistance = 0;
    alpecca.stuckTimer = 0;
    // At a completed target she observes or rests until the next CoreMind
    // directive. There is intentionally no random patrol fallback here.
    if (restPoint && playerNearRestingDistance) {
      alpecca.inspectTimer = 0;
      alpecca.dwellTimer = 0.8;
      setAlpeccaIntent("listening", "player");
      setAlpeccaAnimation("idleDown");
    } else if (!anxious && !settlingIn && alpecca.movementDirectivePending
      && navigation.final && distanceToTarget <= 0.14 && alpecca.inspectTimer <= 0) {
      alpecca.inspectTimer = restPoint ? 9.5 : 3.4;
      announceAlpeccaInspection(explorePoint);
    }
    if (alpecca.inspectTimer > 0) {
      setAlpeccaSpriteFlip(false);
      if (terminalTarget) updateAlpeccaTerminalInteraction(terminalTarget, explorePoint);
      else {
        clearAlpeccaTerminalInteraction();
        setAlpeccaIntent("inspecting", explorePoint.roomName);
        faceAlpeccaToward(explorePoint.lookAt);
        setAlpeccaAnimation(alpeccaInspectionAnimation(explorePoint));
      }
    } else {
      releaseAlpeccaVrmTerminalTarget();
      if (alpecca.intent !== "observing" && alpecca.intent !== "creating") setAlpeccaIntent("idle", "house");
      setAlpeccaSpriteFlip(false);
      setAlpeccaAnimation(emotionalAlpeccaAnimation());
    }
  }

  updateAlpeccaAnimation(dt);
  updateAlpeccaFootShadows(dt);
  updateAlpeccaSpatialPresence(dt, distanceToPlayer, playerEngaged);
  applyAlpeccaBillboardYaw(dt);
  updateAlpeccaCylinderQaDebug();
  renderer.domElement.dataset.alpeccaState = alpecca.state;
  renderer.domElement.dataset.alpeccaFolder = alpecca.activeFolder;
  renderer.domElement.dataset.alpeccaMoving = String(alpecca.moving);
  renderer.domElement.dataset.alpeccaBillboardYaw = alpecca.billboardYaw.toFixed(3);
  publishAlpeccaRuntimeProbe();
  if (window.__HOUSE_DEBUG__?.alpecca) {
    window.__HOUSE_DEBUG__.alpecca.ready = alpecca.ready;
    window.__HOUSE_DEBUG__.alpecca.state = alpecca.state;
    window.__HOUSE_DEBUG__.alpecca.folder = alpecca.activeFolder;
    window.__HOUSE_DEBUG__.alpecca.artBaseUrl = window.__ALPECCA_RUNTIME__?.artBaseUrl ?? "local";
    window.__HOUSE_DEBUG__.alpecca.artAssetMode = window.__ALPECCA_RUNTIME__?.artAssetMode ?? "local-fallback";
    window.__HOUSE_DEBUG__.alpecca.artManifestUrl = window.__ALPECCA_RUNTIME__?.artManifestUrl ?? "";
    window.__HOUSE_DEBUG__.alpecca.matrixAction = window.__ALPECCA_RUNTIME__?.matrixAction ?? "";
    window.__HOUSE_DEBUG__.alpecca.matrixAssetKey = window.__ALPECCA_RUNTIME__?.matrixAssetKey ?? "";
    window.__HOUSE_DEBUG__.alpecca.matrixRequestedKey = window.__ALPECCA_RUNTIME__?.matrixRequestedKey ?? "";
    window.__HOUSE_DEBUG__.alpecca.matrixLoadedKey = window.__ALPECCA_RUNTIME__?.matrixLoadedKey ?? "";
    window.__HOUSE_DEBUG__.alpecca.matrixFallbackState = window.__ALPECCA_RUNTIME__?.matrixFallbackState ?? "";
    window.__HOUSE_DEBUG__.alpecca.matrixFolder = window.__ALPECCA_RUNTIME__?.matrixFolder ?? "";
    window.__HOUSE_DEBUG__.alpecca.matrixFrameCount = window.__ALPECCA_RUNTIME__?.matrixFrameCount ?? 0;
    window.__HOUSE_DEBUG__.alpecca.matrixSourceFamily = window.__ALPECCA_RUNTIME__?.matrixSourceFamily ?? "";
    window.__HOUSE_DEBUG__.alpecca.matrixApprovalStatus = window.__ALPECCA_RUNTIME__?.matrixApprovalStatus ?? "runtime-ok";
    window.__HOUSE_DEBUG__.alpecca.matrixManifestStatus = window.__ALPECCA_RUNTIME__?.matrixManifestStatus ?? "fallback";
    window.__HOUSE_DEBUG__.alpecca.matrixResolution = window.__ALPECCA_RUNTIME__?.matrixResolution ?? "local-fallback";
    window.__HOUSE_DEBUG__.alpecca.matrixLayerPlan = window.__ALPECCA_RUNTIME__?.matrixLayerPlan ?? "";
    window.__HOUSE_DEBUG__.alpecca.matrixFootAnchor = window.__ALPECCA_RUNTIME__?.matrixFootAnchor ?? "";
    window.__HOUSE_DEBUG__.alpecca.matrixContactFrames = window.__ALPECCA_RUNTIME__?.matrixContactFrames ?? "";
    window.__HOUSE_DEBUG__.alpecca.matrixDepthProxy = window.__ALPECCA_RUNTIME__?.matrixDepthProxy ?? "";
    window.__HOUSE_DEBUG__.alpecca.intent = window.__ALPECCA_RUNTIME__?.intent ?? alpecca.intent;
    window.__HOUSE_DEBUG__.alpecca.animationSourceFamily = window.__ALPECCA_RUNTIME__?.animationSourceFamily ?? "";
    window.__HOUSE_DEBUG__.alpecca.animationSourceStatus = window.__ALPECCA_RUNTIME__?.animationSourceStatus ?? "runtime-ok";
    window.__HOUSE_DEBUG__.alpecca.animationSourceFlagged = window.__ALPECCA_RUNTIME__?.animationSourceFlagged ?? false;
    window.__HOUSE_DEBUG__.alpecca.flipX = window.__ALPECCA_RUNTIME__?.flipX ?? alpecca.flipX;
    window.__HOUSE_DEBUG__.alpecca.perceptionTarget = window.__ALPECCA_RUNTIME__?.perceptionTarget ?? alpecca.perceptionTarget;
    window.__HOUSE_DEBUG__.alpecca.frameIndex = window.__ALPECCA_RUNTIME__?.frameIndex ?? 0;
    window.__HOUSE_DEBUG__.alpecca.frameCount = window.__ALPECCA_RUNTIME__?.frameCount ?? 0;
    window.__HOUSE_DEBUG__.alpecca.moving = alpecca.moving;
    window.__HOUSE_DEBUG__.alpecca.direction = alpecca.screenDirection;
    window.__HOUSE_DEBUG__.alpecca.directionCandidate = alpecca.directionCandidate;
    window.__HOUSE_DEBUG__.alpecca.directionCandidateFrames = alpecca.directionCandidateFrames;
    window.__HOUSE_DEBUG__.alpecca.inspecting = alpecca.inspectTimer > 0 ? explorePoint.roomName : "";
    window.__HOUSE_DEBUG__.alpecca.destination = explorePoint.roomName;
    window.__HOUSE_DEBUG__.alpecca.markers = alpeccaExplorePoints.filter((point) => point.marker).length;
    window.__HOUSE_DEBUG__.alpecca.interacting = alpecca.inspectTimer > 0
      ? terminalTarget?.label ?? alpeccaRoomDevices.get(explorePoint.roomId)?.label ?? ""
      : "";
    window.__HOUSE_DEBUG__.alpecca.stuck = alpecca.stuckTimer;
    window.__HOUSE_DEBUG__.alpecca.routeStep = `${Math.min(alpecca.routeStep + 1, alpecca.route.length)}/${alpecca.route.length}`;
    window.__HOUSE_DEBUG__.alpecca.scaleX = alpecca.sprite?.scale.x ?? 1;
    window.__HOUSE_DEBUG__.alpecca.scaleY = alpecca.sprite?.scale.y ?? 1;
    window.__HOUSE_DEBUG__.alpecca.movementLoaded = window.__ALPECCA_RUNTIME__?.movementLoaded ?? 0;
    window.__HOUSE_DEBUG__.alpecca.movementTotal = window.__ALPECCA_RUNTIME__?.movementTotal ?? alpeccaRequiredMovementStates.length;
    window.__HOUSE_DEBUG__.alpecca.movementMissing = window.__ALPECCA_RUNTIME__?.movementMissing ?? [];
    window.__HOUSE_DEBUG__.alpecca.animationLoaded = window.__ALPECCA_RUNTIME__?.animationLoaded ?? 0;
    window.__HOUSE_DEBUG__.alpecca.animationTotal = window.__ALPECCA_RUNTIME__?.animationTotal ?? alpeccaAllAnimationStates.length;
    window.__HOUSE_DEBUG__.alpecca.animationMissing = window.__ALPECCA_RUNTIME__?.animationMissing ?? [];
    window.__HOUSE_DEBUG__.alpecca.talking = window.__ALPECCA_RUNTIME__?.talking ?? false;
    window.__HOUSE_DEBUG__.alpecca.mouthOpen = window.__ALPECCA_RUNTIME__?.mouthOpen ?? 0;
    window.__HOUSE_DEBUG__.alpecca.profileMouthMode = window.__ALPECCA_RUNTIME__?.profileMouthMode ?? "";
    window.__HOUSE_DEBUG__.alpecca.profileTalkFrame = window.__ALPECCA_RUNTIME__?.profileTalkFrame ?? "";
    window.__HOUSE_DEBUG__.alpecca.voiceEngine = window.__ALPECCA_RUNTIME__?.voiceEngine ?? "";
    window.__HOUSE_DEBUG__.alpecca.voiceName = window.__ALPECCA_RUNTIME__?.voiceName ?? "";
    window.__HOUSE_DEBUG__.alpecca.voiceProfile = window.__ALPECCA_RUNTIME__?.voiceProfile ?? "";
    window.__HOUSE_DEBUG__.alpecca.voicePreview = window.__ALPECCA_RUNTIME__?.voicePreview ?? "";
    window.__HOUSE_DEBUG__.alpecca.voicePrimary = window.__ALPECCA_RUNTIME__?.voicePrimary ?? "";
    window.__HOUSE_DEBUG__.alpecca.voiceTempo = window.__ALPECCA_RUNTIME__?.voiceTempo ?? "";
    window.__HOUSE_DEBUG__.alpecca.voiceRate = window.__ALPECCA_RUNTIME__?.voiceRate ?? "";
    window.__HOUSE_DEBUG__.alpecca.voiceSpeed = window.__ALPECCA_RUNTIME__?.voiceSpeed ?? "";
    window.__HOUSE_DEBUG__.alpecca.voiceEmotionTimer = window.__ALPECCA_RUNTIME__?.voiceEmotionTimer ?? 0;
    window.__HOUSE_DEBUG__.alpecca.voiceEmotionState = window.__ALPECCA_RUNTIME__?.voiceEmotionState ?? {};
    window.__HOUSE_DEBUG__.alpecca.freedomAction = window.__ALPECCA_RUNTIME__?.freedomAction ?? "";
    window.__HOUSE_DEBUG__.alpecca.worldTickTimer = window.__ALPECCA_RUNTIME__?.worldTickTimer ?? 0;
    window.__HOUSE_DEBUG__.alpecca.worldTickInFlight = window.__ALPECCA_RUNTIME__?.worldTickInFlight ?? false;
    window.__HOUSE_DEBUG__.alpecca.frameTime = window.__ALPECCA_RUNTIME__?.frameTime ?? 0;
    window.__HOUSE_DEBUG__.alpecca.loopCount = window.__ALPECCA_RUNTIME__?.loopCount ?? 0;
    window.__HOUSE_DEBUG__.alpecca.droppedFrames = window.__ALPECCA_RUNTIME__?.droppedFrames ?? 0;
    window.__HOUSE_DEBUG__.alpecca.profileMode = window.__ALPECCA_RUNTIME__?.profileMode ?? "";
    window.__HOUSE_DEBUG__.alpecca.profileExpression = window.__ALPECCA_RUNTIME__?.profileExpression ?? "";
    window.__HOUSE_DEBUG__.alpecca.activeFeature = window.__ALPECCA_RUNTIME__?.activeFeature ?? "";
    window.__HOUSE_DEBUG__.alpecca.lastSeen = window.__ALPECCA_RUNTIME__?.lastSeen ?? "";
    window.__HOUSE_DEBUG__.alpecca.lastQuestion = window.__ALPECCA_RUNTIME__?.lastQuestion ?? "";
    window.__HOUSE_DEBUG__.alpecca.animationLock = Math.max(0, alpecca.animationLockTimer);
    window.__HOUSE_DEBUG__.alpecca.dwell = Math.max(0, alpecca.dwellTimer);
    window.__HOUSE_DEBUG__.alpecca.walkPause = Math.max(0, alpecca.walkPauseTimer);
    window.__HOUSE_DEBUG__.alpecca.groundContact = alpecca.groundContactIntensity;
    window.__HOUSE_DEBUG__.alpecca.floorReflection = alpecca.floorReflectionIntensity;
    window.__HOUSE_DEBUG__.alpecca.debugLocked = alpecca.showcaseTimer > 0;
    window.__HOUSE_DEBUG__.alpecca.debugLockState = alpecca.showcaseTimer > 0 ? alpecca.showcaseState : "";
    window.__HOUSE_DEBUG__.alpecca.viewVertical = window.__ALPECCA_RUNTIME__?.viewVertical ?? alpeccaLastViewMatrix.vertical;
    window.__HOUSE_DEBUG__.alpecca.viewHorizontal = window.__ALPECCA_RUNTIME__?.viewHorizontal ?? alpeccaLastViewMatrix.horizontal;
    window.__HOUSE_DEBUG__.alpecca.viewMatrix = window.__ALPECCA_RUNTIME__?.viewMatrix ?? alpeccaLastViewMatrix.key;
    window.__HOUSE_DEBUG__.alpecca.relativeYawDeg = window.__ALPECCA_RUNTIME__?.relativeYawDeg ?? alpeccaLastViewMatrix.relativeYawDeg;
    window.__HOUSE_DEBUG__.alpecca.cameraPitchDeg = window.__ALPECCA_RUNTIME__?.cameraPitchDeg ?? alpeccaLastViewMatrix.cameraPitchDeg;
    window.__HOUSE_DEBUG__.alpecca.viewVolumeZone = window.__ALPECCA_RUNTIME__?.viewVolumeZone ?? alpeccaLastViewMatrix.volumeZone;
    window.__HOUSE_DEBUG__.alpecca.viewVolumeProbe = window.__ALPECCA_RUNTIME__?.viewVolumeProbe ?? alpeccaLastViewMatrix.volumeProbe;
    window.__HOUSE_DEBUG__.alpecca.viewVolumeDepth = window.__ALPECCA_RUNTIME__?.viewVolumeDepth ?? alpeccaLastViewMatrix.volumeDepth;
    window.__HOUSE_DEBUG__.alpecca.viewSampleY = window.__ALPECCA_RUNTIME__?.viewSampleY ?? alpeccaLastViewMatrix.sampleY;
    window.__HOUSE_DEBUG__.alpecca.viewSector16 = window.__ALPECCA_RUNTIME__?.viewSector16 ?? alpeccaLastViewMatrix.sector16;
    window.__HOUSE_DEBUG__.alpecca.viewSector16Key = window.__ALPECCA_RUNTIME__?.viewSector16Key ?? alpeccaLastViewMatrix.sector16Key;
    window.__HOUSE_DEBUG__.alpecca.cylinderRadius = window.__ALPECCA_RUNTIME__?.cylinderRadius ?? alpeccaLastViewMatrix.cylinderRadius;
    window.__HOUSE_DEBUG__.alpecca.cylinderZone = window.__ALPECCA_RUNTIME__?.cylinderZone ?? alpeccaLastViewMatrix.cylinderZone;
    window.__HOUSE_DEBUG__.alpecca.cylinderPlayerAngleDeg = window.__ALPECCA_RUNTIME__?.cylinderPlayerAngleDeg ?? alpeccaLastViewMatrix.relativeYawDeg;
    window.__HOUSE_DEBUG__.alpecca.cylinderPlayerDistance = window.__ALPECCA_RUNTIME__?.cylinderPlayerDistance ?? alpeccaLastViewMatrix.cylinderPlayerDistance;
    window.__HOUSE_DEBUG__.alpecca.cylinderVerticalTier = window.__ALPECCA_RUNTIME__?.cylinderVerticalTier ?? alpeccaLastViewMatrix.vertical;
    window.__HOUSE_DEBUG__.alpecca.cylinderMovementClamped = window.__ALPECCA_RUNTIME__?.cylinderMovementClamped ?? alpeccaCylinderMovementClamped;
    window.__HOUSE_DEBUG__.alpecca.cylinderQaVisible = window.__ALPECCA_RUNTIME__?.cylinderQaVisible ?? !!alpeccaCylinderQaGroup?.visible;
    window.__HOUSE_DEBUG__.alpecca.billboardMode = window.__ALPECCA_RUNTIME__?.billboardMode ?? "volume-soft-billboard";
    window.__HOUSE_DEBUG__.alpecca.billboardClampDeg = window.__ALPECCA_RUNTIME__?.billboardClampDeg ?? alpeccaLastViewMatrix.billboardClampDeg;
    window.__HOUSE_DEBUG__.alpecca.stageRoom = window.__ALPECCA_RUNTIME__?.stageRoom ?? "";
    window.__HOUSE_DEBUG__.alpecca.stagePad = window.__ALPECCA_RUNTIME__?.stagePad ?? "";
    window.__HOUSE_DEBUG__.alpecca.stageQaIssues = window.__ALPECCA_RUNTIME__?.stageQaIssues ?? alpeccaStageQaIssues;
    window.__HOUSE_DEBUG__.alpecca.navClearance = window.__ALPECCA_RUNTIME__?.navClearance ?? alpeccaNavClearanceLabel();
    window.__HOUSE_DEBUG__.alpecca.heightClass = window.__ALPECCA_RUNTIME__?.heightClass ?? alpeccaHeightClass(alpecca.state);
    window.__HOUSE_DEBUG__.alpecca.standingScaleLocked = window.__ALPECCA_RUNTIME__?.standingScaleLocked ?? isAlpeccaStandingHeightClass(alpecca.state);
    window.__HOUSE_DEBUG__.alpecca.silhouetteWidth = window.__ALPECCA_RUNTIME__?.silhouetteWidth ?? 0;
    window.__HOUSE_DEBUG__.alpecca.legWidthRatio = window.__ALPECCA_RUNTIME__?.legWidthRatio ?? 0;
    window.__HOUSE_DEBUG__.alpecca.walkPlaybackRate = window.__ALPECCA_RUNTIME__?.walkPlaybackRate ?? alpecca.walkPlaybackRate;
    window.__HOUSE_DEBUG__.alpecca.walkSpeed = window.__ALPECCA_RUNTIME__?.walkSpeed ?? alpecca.walkSpeed;
    window.__HOUSE_DEBUG__.alpecca.x = alpecca.group.position.x;
    window.__HOUSE_DEBUG__.alpecca.z = alpecca.group.position.z;
  }
}

function createAlpeccaFallback() {
  const fallback = new THREE.Mesh(
    new THREE.PlaneGeometry(1.35, 1.7),
    new THREE.MeshBasicMaterial({ color: "#d86a8d", transparent: true, opacity: 0.92, side: THREE.DoubleSide }),
  );
  fallback.position.set(0, 0.89, 0);
  alpecca.group.add(fallback);
  addAlpeccaHitTarget();
  addAlpeccaGroundShadow();
  alpecca.ready = true;
  publishAlpeccaRuntimeProbe();
  consumeManualStepHash();
}

function addAlpeccaHitTarget() {
  const target = new THREE.Mesh(
    new THREE.PlaneGeometry(2.05, 2.15),
    new THREE.MeshBasicMaterial({ color: "#ffffff", transparent: true, opacity: 0, depthWrite: false, side: THREE.DoubleSide }),
  );
  target.name = "Alpecca interaction target";
  target.position.set(0, 1.08, 0);
  alpecca.group.add(target);
  alpecca.hitTarget = target;
}

async function createAlpecca() {
  alpecca.group.name = "Alpecca NPC";
  if (!restoreAlpeccaPose()) alpecca.group.position.copy(currentAlpeccaExplorePoint().position);
  scene.add(alpecca.group);
  // Fetch and parse her 3D body in parallel with sprite startup. The sprite
  // remains visible until activation, so boot stays responsive while the
  // first embodiment switch gains the same cached path as later switches.
  prewarmAlpeccaVrm();
  publishAlpeccaRuntimeProbe();

  window.__HOUSE_DEBUG__!.alpecca = {
    ready: false,
    state: alpecca.state,
    folder: alpecca.activeFolder,
    artBaseUrl: alpeccaArtBaseUrl || "local",
    artAssetMode: alpeccaArtAssetMode,
    artManifestUrl: alpeccaAssetSourceManifestUrl,
    matrixAction: "idle",
    matrixAssetKey: "idle_eye_front_native_pending",
    matrixRequestedKey: "idle_eye_front_native_pending",
    matrixLoadedKey: "idle_eye_front_idleDown",
    matrixFallbackState: "idleDown",
    matrixFolder: alpeccaAnimationConfig.idleDown.folder,
    matrixFrameCount: 0,
    matrixSourceFamily: "iso",
    matrixApprovalStatus: "approved",
    matrixManifestStatus: "pending",
    matrixResolution: "local-fallback",
    intent: alpecca.intent,
    animationSourceFamily: "",
    animationSourceStatus: "approved",
    animationSourceFlagged: false,
    flipX: false,
    perceptionTarget: "",
    frameIndex: 0,
    frameCount: 0,
    moving: false,
    direction: alpecca.screenDirection,
    directionCandidate: alpecca.directionCandidate,
    directionCandidateFrames: alpecca.directionCandidateFrames,
    inspecting: "",
    destination: currentAlpeccaExplorePoint().roomName,
    markers: 0,
    interacting: "",
    stuck: 0,
    routeStep: "0/0",
    scaleX: 1,
    scaleY: 1,
    movementLoaded: 0,
    movementTotal: alpeccaRequiredMovementStates.length,
    movementMissing: [...alpeccaRequiredMovementStates],
    animationLoaded: 0,
    animationTotal: alpeccaAllAnimationStates.length,
    animationMissing: [...alpeccaAllAnimationStates],
    talking: false,
    mouthOpen: 0,
    profileMouthMode: "fallback-overlay",
    profileTalkFrame: "",
    frameTime: 0,
    loopCount: 0,
    droppedFrames: 0,
    profileMode: alpeccaProfileMode,
    profileExpression: "",
    activeFeature: "",
    lastSeen: "",
    lastQuestion: "",
    animationLock: 0,
    dwell: 0,
    walkPause: 0,
    groundContact: 0,
    floorReflection: 0,
    debugLocked: false,
    debugLockState: "",
    viewVertical: alpeccaLastViewMatrix.vertical,
    viewHorizontal: alpeccaLastViewMatrix.horizontal,
    viewMatrix: alpeccaLastViewMatrix.key,
    relativeYawDeg: alpeccaLastViewMatrix.relativeYawDeg,
    cameraPitchDeg: alpeccaLastViewMatrix.cameraPitchDeg,
    viewVolumeZone: alpeccaLastViewMatrix.volumeZone,
    viewVolumeProbe: alpeccaLastViewMatrix.volumeProbe,
    viewVolumeDepth: alpeccaLastViewMatrix.volumeDepth,
    viewSampleY: alpeccaLastViewMatrix.sampleY,
    viewSector16: alpeccaLastViewMatrix.sector16,
    viewSector16Key: alpeccaLastViewMatrix.sector16Key,
    cylinderRadius: alpeccaLastViewMatrix.cylinderRadius,
    cylinderZone: alpeccaLastViewMatrix.cylinderZone,
    cylinderPlayerAngleDeg: alpeccaLastViewMatrix.relativeYawDeg,
    cylinderPlayerDistance: alpeccaLastViewMatrix.cylinderPlayerDistance,
    cylinderVerticalTier: alpeccaLastViewMatrix.vertical,
    cylinderMovementClamped: false,
    cylinderQaVisible: false,
    billboardMode: "volume-soft-billboard",
    billboardClampDeg: alpeccaLastViewMatrix.billboardClampDeg,
    stageRoom: "entry",
    stagePad: alpeccaStagePadLabelForPosition(alpecca.group.position.x, alpecca.group.position.z),
    stageQaIssues: alpeccaStageQaIssues,
    navClearance: "unchecked",
    heightClass: "standing",
    standingScaleLocked: true,
    silhouetteWidth: 0,
    legWidthRatio: 0,
    walkPlaybackRate: alpeccaWalkFrameRate,
    walkSpeed: 0,
    x: alpecca.group.position.x,
    z: alpecca.group.position.z,
  };

  try {
    const idleConfig = alpeccaAnimationConfig.idle;
    await loadAlpeccaAnimation("idle", idleConfig.folder, idleConfig.secondsPerFrame, idleConfig.loop ?? true);
    await Promise.all(alpeccaStartupMovementStates.map((name) => ensureAlpeccaAnimation(name)));

    const sprite = new THREE.Mesh(new THREE.PlaneGeometry(alpeccaSpritePlaneSize, alpeccaSpritePlaneSize), alpecca.material);
    sprite.name = "Alpecca sprite";
    sprite.position.set(0, 0.93, 0);
    sprite.renderOrder = 8;
    sprite.castShadow = false;
    alpecca.group.add(sprite);
    alpecca.sprite = sprite;
    addAlpeccaDepthLayers(sprite);
    addAlpeccaHeightRuler();
    addAlpeccaGlitchLayers(sprite);
    addAlpeccaHeadLook();
    addAlpeccaHitTarget();
    addAlpeccaGroundShadow();
    setAlpeccaAnimation("idleDown");
    applyAlpeccaBillboardYaw(0, true);
    preloadAlpeccaMovementAnimations();
    alpecca.ready = true;
    publishAlpeccaRuntimeProbe();
    consumeManualStepHash();
    if (configuredAlpeccaEmbodiment() === "vrm") void activateAlpeccaVrm();
  } catch (error) {
    console.warn("Alpecca sprite assets failed to load. Using fallback NPC.", error);
    createAlpeccaFallback();
  }

  alpeccaInteractable = {
    id: "alpecca",
    label: "Talk to Alpecca",
    root: alpecca.group,
    range: 2.4,
    type: "momentary",
    onUse: () => {
      focusAlpecca(3.5, "idleDown");
      openAlpeccaChat();
      return "";
    },
  };
  register(alpeccaInteractable);
}

function addSofa() {
  const group = new THREE.Group();
  group.name = "Alpecca recovery sofa";
  group.position.set(-6.05, 0, 4.62);
  scene.add(group);
  group.add(makeBox([2.6, 0.55, 0.8], [0, 0.35, 0], materials.fabric));
  group.add(makeBox([2.75, 0.75, 0.22], [0, 0.72, 0.43], materials.fabric));
  group.add(makeBox([0.24, 0.55, 0.86], [-1.42, 0.48, 0], materials.fabric));
  group.add(makeBox([0.24, 0.55, 0.86], [1.42, 0.48, 0], materials.fabric));
  group.add(makeBox([0.58, 0.12, 0.38], [-0.72, 0.68, -0.1], materials.accentPanel));
  group.add(makeBox([1.24, 0.06, 0.5], [0.42, 0.66, -0.05], materials.screen));
  register({
    id: "alpecca-rest-nook",
    label: "Inspect Alpecca rest nook",
    root: group,
    range: 1.9,
    type: "momentary",
    onUse: () => {
      pulseAlpeccaRoomDevice("hq-control", 2.4);
      return "Alpecca's rest nook is where she can intentionally sleep, recharge, and return when you approach.";
    },
  });
  addFurnitureCollider(-6.05, 4.62, 3.0, 0.95);
}

function addCoffeeTable() {
  const table = new THREE.Group();
  table.position.set(-4.3, 0, 2.2);
  scene.add(table);
  table.add(makeBox([1.7, 0.13, 0.85], [0, 0.55, 0], materials.lightWood));
  for (const x of [-0.72, 0.72]) for (const z of [-0.33, 0.33]) table.add(makeBox([0.1, 0.55, 0.1], [x, 0.27, z], materials.darkWood));
  addFurnitureCollider(-4.3, 2.2, 1.9, 1.0);
}

function addKitchen() {
  box("observatory media counter", [4.45, 0.9, 0.74], [5.0, 0.45, 5.22], materials.lightWood);
  box("observatory counter top", [4.55, 0.12, 0.82], [5.0, 0.96, 5.22], materials.metal);
  const mediaRack = box("observatory equipment rack", [0.9, 2.0, 0.78], [7.15, 1, 3.35], new THREE.MeshStandardMaterial({ color: "#dbe4e2", roughness: 0.36 }));
  box("observatory storage module", [0.9, 0.8, 0.75], [3.25, 0.42, 5.17], new THREE.MeshStandardMaterial({ color: "#44494a", roughness: 0.4 }));
  addFurnitureCollider(5.0, 5.2, 4.75, 0.95);
  addFurnitureCollider(7.15, 3.35, 1.05, 0.98);

  register({
    id: "observatory-rack",
    label: "Inspect observatory rack",
    root: mediaRack,
    range: 2,
    type: "momentary",
    onUse: () => "The rack is labeled: creative review feeds, media deck, and live source monitor.",
  });
}

function addBedroom() {
  const readingTable = new THREE.Group();
  readingTable.position.set(-5.18, 0, -4.72);
  scene.add(readingTable);
  readingTable.add(makeBox([2.15, 0.14, 0.82], [0, 0.72, 0], materials.darkWood));
  readingTable.add(makeBox([0.12, 0.7, 0.12], [-0.88, 0.36, -0.28], materials.darkWood));
  readingTable.add(makeBox([0.12, 0.7, 0.12], [0.88, 0.36, -0.28], materials.darkWood));
  readingTable.add(makeBox([1.68, 0.05, 0.52], [0, 0.82, 0], materials.paper));
  addFurnitureCollider(-5.18, -4.72, 2.35, 0.98);

  const wardrobe = box("archive cabinet", [1.18, 1.88, 0.62], [-3.05, 0.94, -5.02], materials.darkWood);
  addFurnitureCollider(-3.05, -5.02, 1.38, 0.82);
  register({
    id: "archive-cabinet",
    label: "Open archive cabinet",
    root: wardrobe,
    range: 1.8,
    type: "toggle",
    active: false,
    onUse: (item) => {
      item.active = !item.active;
      wardrobe.scale.x = item.active ? 1.08 : 1;
      return item.active ? "The archive cabinet slides open with labeled memory folders." : "Archive cabinet closed.";
    },
  });
}

function addBathroom() {
  box("workshop utility cabinet", [1.12, 0.82, 0.58], [7.04, 0.41, -4.92], materials.trim);
  const sink = cylinder("prototype rinse tray", 0.33, 0.12, [7.04, 0.89, -4.92], new THREE.MeshStandardMaterial({ color: "#f4f7f4", roughness: 0.38 }));
  sink.scale.z = 0.7;
  box("workshop tool storage", [0.92, 1.52, 0.55], [7.12, 0.76, -2.62], materials.darkWood);
  box("workshop parts board", [1.15, 0.92, 0.05], [6.92, 1.62, -5.66], materials.board);
  addFurnitureCollider(7.04, -4.92, 1.32, 0.78);
  addFurnitureCollider(7.12, -2.62, 1.08, 0.72);
  register({
    id: "prototype-rinse-tray",
    label: "Rinse prototype tray",
    root: sink,
    range: 1.7,
    type: "momentary",
    onUse: () => "The tray rinses off a prototype part and drains quietly.",
  });
}

function addDesk() {
  const desk = new THREE.Group();
  desk.position.set(-6.45, 0, -0.1);
  scene.add(desk);
  desk.add(makeBox([1.8, 0.13, 0.78], [0, 0.78, 0], materials.darkWood));
  desk.add(makeBox([0.2, 0.75, 0.2], [-0.72, 0.38, -0.24], materials.darkWood));
  desk.add(makeBox([0.2, 0.75, 0.2], [0.72, 0.38, -0.24], materials.darkWood));
  desk.add(makeBox([1.55, 0.42, 0.12], [0, 0.52, 0.33], materials.lightWood));
  addFurnitureCollider(-6.45, -0.1, 2.1, 1.0);
  register({
    id: "drawer",
    label: "Open desk drawer",
    root: desk,
    range: 1.8,
    type: "toggle",
    active: false,
    onUse: (item) => {
      item.active = !item.active;
      return item.active ? "The drawer slides out with a letter inside." : "Drawer closed.";
    },
    update: (dt, item) => {
      const drawer = desk.children[3];
      drawer.position.z = THREE.MathUtils.damp(drawer.position.z, item.active ? 0.7 : 0.33, 8, dt);
    },
  });
}

function addLamps() {
  addLamp("hq standing lamp", [-2.32, 0, 5.05], true);
  addLamp("library reading lamp", [-2.42, 0, -5.08], false);
  addContactOcclusion("hq standing lamp foot ao", [0.8, 0.8], [-2.32, 0.012, 5.05], 0.18);
  addContactOcclusion("library reading lamp foot ao", [0.58, 0.58], [-2.42, 0.012, -5.08], 0.16);
}

function addLamp(id: string, pos: THREE.Vector3Tuple, startsOn: boolean) {
  const group = new THREE.Group();
  group.position.set(...pos);
  scene.add(group);
  const base = new THREE.Mesh(new THREE.CylinderGeometry(0.26, 0.3, 0.08, 28), materials.metal);
  base.position.set(0, 0.04, 0);
  base.castShadow = true;
  base.receiveShadow = true;
  group.add(base);

  const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.035, 0.045, 1.22, 18), materials.metal);
  pole.position.set(0, 0.67, 0);
  pole.castShadow = true;
  group.add(pole);

  const neck = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.025, 0.28, 14), materials.metal);
  neck.position.set(0.12, 1.22, 0);
  neck.rotation.z = -0.45;
  neck.castShadow = true;
  group.add(neck);

  const shadeMaterial = materials.glow.clone();
  shadeMaterial.opacity = startsOn ? 0.86 : 0.5;
  shadeMaterial.transparent = true;
  const shade = new THREE.Mesh(new THREE.CylinderGeometry(0.24, 0.36, 0.32, 28, 1, true), shadeMaterial);
  shade.name = `${id} shade`;
  shade.position.set(0.18, 1.36, 0);
  shade.castShadow = true;
  group.add(shade);

  const bulb = new THREE.Mesh(new THREE.SphereGeometry(0.09, 18, 12), materials.glow);
  bulb.position.set(0.18, 1.29, 0);
  group.add(bulb);

  const light = new THREE.PointLight("#ffd98a", startsOn ? 1.2 : 0, 7, 2);
  light.position.set(pos[0] + 0.18, 1.3, pos[2]);
  light.castShadow = true;
  scene.add(light);
  const lampItem: Interactable = {
    id,
    label: id.includes("reading") ? "Switch reading lamp" : "Switch lamp",
    root: group,
    range: 1.9,
    type: "toggle",
    active: startsOn,
    onUse: (item) => {
      item.active = !item.active;
      light.intensity = item.active ? 1.2 : 0;
      shadeMaterial.opacity = item.active ? 0.86 : 0.42;
      return item.active ? "The lamp warms the room." : "The lamp clicks off.";
    },
  };
  register(lampItem);
  alpeccaHomeSystems.push({
    id: `lamp-${id}`,
    kind: "lamp",
    roomId: officeRoomAtPosition(pos[0], pos[2]).id,
    label: id,
    root: group,
    item: lampItem,
    pulseTimer: 0,
    cooldown: startsOn ? 12 : 0,
  });
}

function addKeepsakes() {
  addKeepsake("old-photo", "Take old photo", [-4.28, 0.72, 2.18], "A faded photo of the house on moving day.");
  addKeepsake("brass-key", "Pick up brass key", [-6.55, 0.95, -0.12], "A brass key with no matching lock.");
  addKeepsake("music-box", "Wind music box", [-5.25, 0.96, -4.15], "A tiny music box plays three careful notes.");
  addKeepsake("porcelain-cup", "Take porcelain cup", [4.72, 0.96, 5.18], "A porcelain cup, still faintly warm.");
}

function addKeepsake(id: string, label: string, pos: THREE.Vector3Tuple, message: string) {
  const group = new THREE.Group();
  group.position.set(...pos);
  scene.add(group);
  const plinth = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.24, 0.05, 18), materials.metal);
  plinth.position.y = -0.04;
  plinth.castShadow = true;
  plinth.receiveShadow = true;
  group.add(plinth);
  const gem = new THREE.Mesh(new THREE.DodecahedronGeometry(0.17, 0), materials.keepsake);
  gem.position.y = 0.16;
  gem.castShadow = true;
  group.add(gem);
  const halo = new THREE.PointLight("#ffd06d", 0.55, 2.2, 2);
  group.add(halo);
  register({
    id,
    label,
    root: group,
    range: 1.7,
    type: "collect",
    collected: false,
    onUse: (item) => {
      if (item.collected) return "";
      item.collected = true;
      item.root.visible = false;
      foundKeepsakes += 1;
      foundEl.textContent = String(foundKeepsakes);
      if (foundKeepsakes === 4) return "All keepsakes found. The house feels awake.";
      return message;
    },
    update: (dt, item) => {
      if (item.collected) return;
      item.root.rotation.y += dt * 1.5;
      item.root.position.y = pos[1];
    },
  });
}

function makeBox(size: THREE.Vector3Tuple, pos: THREE.Vector3Tuple, mat: THREE.Material) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), mat);
  mesh.position.set(...pos);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  return mesh;
}

function addContactOcclusion(name: string, size: THREE.Vector2Tuple, pos: THREE.Vector3Tuple, opacity = 0.2) {
  const material = aoMaterial.clone();
  material.opacity = opacity;
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(size[0], size[1]), material);
  mesh.name = name;
  mesh.rotation.x = -Math.PI / 2;
  mesh.position.set(pos[0], 0.012, pos[2]);
  mesh.renderOrder = 1;
  scene.add(mesh);
  return mesh;
}

function addRoomCornerOcclusion() {
  const strips: Array<[string, THREE.Vector2Tuple, THREE.Vector3Tuple, number]> = [
    ["north wall floor ao", [15.2, 0.35], [0, 0.012, -5.55], 0.16],
    ["south wall floor ao", [15.2, 0.35], [0, 0.012, 5.55], 0.16],
    ["west wall floor ao", [0.35, 11.2], [-7.55, 0.012, 0], 0.16],
    ["east wall floor ao", [0.35, 11.2], [7.55, 0.012, 0], 0.16],
    ["hall divider ao", [0.3, 8.5], [-1.55, 0.012, -0.35], 0.12],
    ["right divider ao", [0.3, 7.5], [2.05, 0.012, -1.2], 0.12],
  ];
  for (const [name, size, pos, opacity] of strips) addContactOcclusion(name, size, pos, opacity);
}

function addFurnitureOcclusion() {
  return;
}

function createLighting() {
  if (isPrototypeMode()) {
    scene.add(new THREE.HemisphereLight("#5f8790", "#050404", 0.18));
    const voidFill = new THREE.AmbientLight("#233034", 0.16);
    scene.add(voidFill);
    const rim = new THREE.DirectionalLight("#8eeeff", 0.42);
    rim.position.set(-3.5, 5.2, -4.2);
    scene.add(rim);
    return;
  }
  scene.add(new THREE.HemisphereLight("#eef8ff", "#6d6659", 0.82));
  const roomFill = new THREE.AmbientLight("#f5f1e6", 0.26);
  scene.add(roomFill);
  const sun = new THREE.DirectionalLight("#fff2d8", 1.32);
  sun.position.set(-6, 9, 6);
  sun.castShadow = false;
  scene.add(sun);
  const coolRim = new THREE.DirectionalLight("#c6e8ff", 0.34);
  coolRim.position.set(6, 5, -5);
  coolRim.castShadow = false;
  scene.add(coolRim);
}

function createYardHint() {
  if (isPrototypeMode()) return;
  box("porch slab", [3.0, 0.12, 1.4], [0.55, -0.05, 6.65], new THREE.MeshStandardMaterial({ color: "#a5a39a", roughness: 0.88 }), false);
  box("front path", [1.2, 0.06, 8.5], [0.55, -0.08, 10.5], new THREE.MeshStandardMaterial({ color: "#7d8178", roughness: 0.9 }), false);
}

function getTarget() {
  raycaster.setFromCamera(centerRay, camera);
  const hits = raycaster.intersectObjects(interactableObjects, false);
  let alpeccaCandidateItem: Interactable | null = null;
  for (const hit of hits) {
    const item = interactableMeshes.get(hit.object.uuid);
    if (!item || item.collected) continue;
    const distance = camera.position.distanceTo(item.root.getWorldPosition(targetWorldPosition));
    if (distance > item.range) continue;
    if (item.id === "alpecca") {
      alpeccaCandidateItem = item;
      continue;
    }
    return item;
  }
  return alpeccaCandidateItem;
}

function collides(x: number, z: number) {
  return walls.some((wall) => x + playerRadius > wall.minX && x - playerRadius < wall.maxX && z + playerRadius > wall.minZ && z - playerRadius < wall.maxZ);
}

function alpeccaCollides(x: number, z: number) {
  const radius = 0.3;
  return walls.some((wall) => x + radius > wall.minX && x - radius < wall.maxX && z + radius > wall.minZ && z - radius < wall.maxZ);
}

function constrainAlpeccaToStageCylinder(candidate: THREE.Vector3) {
  alpeccaCylinderMovementClamped = false;
  if (!isAlpeccaCylinderQaMode()) return;
  const spec = alpeccaStageSpecForPosition(alpecca.group.position.x, alpecca.group.position.z);
  const center = spec.stagePad.center;
  const radius = Math.max(alpeccaCylinderStageRadius, Math.min(spec.stagePad.size.x, spec.stagePad.size.y) * 0.5);
  const dx = candidate.x - center.x;
  const dz = candidate.z - center.z;
  const distance = Math.hypot(dx, dz);
  if (distance <= radius || distance <= 0.001) return;
  candidate.x = center.x + (dx / distance) * radius;
  candidate.z = center.z + (dz / distance) * radius;
  alpeccaCylinderMovementClamped = true;
}

function senseAlpeccaAvoidance(dir: THREE.Vector3, dt: number) {
  alpeccaAvoidance.set(0, 0, 0);
  const x = alpecca.group.position.x;
  const z = alpecca.group.position.z;

  for (const wall of walls) {
    const nearestX = THREE.MathUtils.clamp(x, wall.minX, wall.maxX);
    const nearestZ = THREE.MathUtils.clamp(z, wall.minZ, wall.maxZ);
    const awayX = x - nearestX;
    const awayZ = z - nearestZ;
    const distance = Math.hypot(awayX, awayZ);
    if (distance > 0.001 && distance < 0.72) {
      const strength = (0.72 - distance) / 0.72;
      alpeccaAvoidance.x += (awayX / distance) * strength;
      alpeccaAvoidance.z += (awayZ / distance) * strength;
    }
  }

  const playerAwayX = x - camera.position.x;
  const playerAwayZ = z - camera.position.z;
  const playerDistance = Math.hypot(playerAwayX, playerAwayZ);
  if (playerDistance > 0.001 && playerDistance < 1.35) {
    const strength = (1.35 - playerDistance) / 1.35;
    alpeccaAvoidance.x += (playerAwayX / playerDistance) * strength * 1.4;
    alpeccaAvoidance.z += (playerAwayZ / playerDistance) * strength * 1.4;
  }

  if (alpeccaAvoidance.lengthSq() > 0.0001) {
    dir.addScaledVector(alpeccaAvoidance.normalize(), 0.75).normalize();
    alpecca.avoidTimer = 0.55;
  } else if (alpecca.avoidTimer > 0) {
    alpecca.avoidTimer -= dt;
  }
}

function moveAlpeccaSafely(dir: THREE.Vector3, distance: number) {
  alpeccaCandidate.copy(alpecca.group.position).addScaledVector(dir, distance);
  constrainAlpeccaToStageCylinder(alpeccaCandidate);
  if (!alpeccaCollides(alpeccaCandidate.x, alpeccaCandidate.z)) {
    alpecca.group.position.copy(alpeccaCandidate);
    return true;
  }

  alpeccaSideStep.set(dir.z, 0, -dir.x).normalize();
  alpeccaCandidate.copy(alpecca.group.position).addScaledVector(alpeccaSideStep, distance * 0.75);
  constrainAlpeccaToStageCylinder(alpeccaCandidate);
  if (!alpeccaCollides(alpeccaCandidate.x, alpeccaCandidate.z)) {
    alpecca.group.position.copy(alpeccaCandidate);
    return true;
  }

  alpeccaSideStep.set(-dir.z, 0, dir.x).normalize();
  alpeccaCandidate.copy(alpecca.group.position).addScaledVector(alpeccaSideStep, distance * 0.75);
  constrainAlpeccaToStageCylinder(alpeccaCandidate);
  if (!alpeccaCollides(alpeccaCandidate.x, alpeccaCandidate.z)) {
    alpecca.group.position.copy(alpeccaCandidate);
    return true;
  }

  return false;
}

function constrainPlayerToHouse() {
  if (isPrototypeMode()) {
    camera.position.x = THREE.MathUtils.clamp(camera.position.x, -5.25, 5.25);
    camera.position.z = THREE.MathUtils.clamp(camera.position.z, -5.25, 5.25);
    return;
  }
  camera.position.x = THREE.MathUtils.clamp(camera.position.x, -7.28, 7.28);
  camera.position.z = THREE.MathUtils.clamp(camera.position.z, -5.28, 4.72);
}

function movePlayer(dt: number) {
  const input = new THREE.Vector3(
    Number(keys.has("KeyD")) - Number(keys.has("KeyA")) + virtualMove.x,
    0,
    Number(keys.has("KeyS")) - Number(keys.has("KeyW")) + virtualMove.z,
  );
  if (input.lengthSq() > 0) input.normalize();

  const forward = new THREE.Vector3(Math.sin(player.yaw), 0, Math.cos(player.yaw));
  const right = new THREE.Vector3(forward.z, 0, -forward.x);
  const desired = right.multiplyScalar(input.x).add(forward.multiplyScalar(input.z));
  const speed = keys.has("ShiftLeft") || keys.has("ShiftRight") ? 4.0 : 2.45;
  const step = desired.multiplyScalar(speed * dt);

  const nextX = camera.position.x + step.x;
  const nextZ = camera.position.z + step.z;
  if (!collides(nextX, camera.position.z)) camera.position.x = nextX;
  if (!collides(camera.position.x, nextZ)) camera.position.z = nextZ;
  constrainPlayerToHouse();
  if (isAlpeccaVrm3D() && alpecca.ready) {
    // Her 3D body is solid: push the player out of her body cylinder, respecting walls.
    const bodyDx = camera.position.x - alpecca.group.position.x;
    const bodyDz = camera.position.z - alpecca.group.position.z;
    const bodyDistance = Math.hypot(bodyDx, bodyDz);
    if (bodyDistance > 0.0001 && bodyDistance < alpeccaCylinderBodyRadius) {
      const push = alpeccaCylinderBodyRadius - bodyDistance;
      const pushX = camera.position.x + (bodyDx / bodyDistance) * push;
      const pushZ = camera.position.z + (bodyDz / bodyDistance) * push;
      if (!collides(pushX, camera.position.z)) camera.position.x = pushX;
      if (!collides(camera.position.x, pushZ)) camera.position.z = pushZ;
    }
  }

  const moving = input.lengthSq() > 0;
  player.bob += moving ? dt * speed * 5.5 : dt * 2;
  camera.position.y = 1.55 + (moving ? Math.sin(player.bob) * 0.025 : Math.sin(player.bob) * 0.006);
  camera.rotation.set(player.pitch, player.yaw, 0, "YXZ");
  if (prototypePlayerSpotlight) {
    prototypePlayerSpotlight.position.x = THREE.MathUtils.damp(prototypePlayerSpotlight.position.x, camera.position.x, 7, dt);
    prototypePlayerSpotlight.position.z = THREE.MathUtils.damp(prototypePlayerSpotlight.position.z, camera.position.z, 7, dt);
    prototypePlayerSpotlight.target.position.x = prototypePlayerSpotlight.position.x;
    prototypePlayerSpotlight.target.position.z = prototypePlayerSpotlight.position.z;
  }
  renderer.domElement.dataset.playerX = camera.position.x.toFixed(3);
  renderer.domElement.dataset.playerZ = camera.position.z.toFixed(3);
}

function updateKeyboardLook(dt: number) {
  const yawInput = Number(keys.has("ArrowRight")) - Number(keys.has("ArrowLeft"));
  const pitchInput = Number(keys.has("ArrowDown")) - Number(keys.has("ArrowUp"));
  if (yawInput === 0 && pitchInput === 0) return;

  player.yaw -= yawInput * 2.2 * dt;
  player.pitch -= pitchInput * 1.7 * dt;
  player.pitch = THREE.MathUtils.clamp(player.pitch, -1.15, 1.15);
}

function updateHud(dt: number) {
  if (alpeccaAiRetryTimer > 0) {
    alpeccaAiRetryTimer -= dt;
    if (alpeccaAiRetryTimer <= 0) connectAlpeccaAi();
  }

  if (alpeccaAiAwaitingReply && alpeccaAiReplyStartedAt > 0) {
    const waitingMs = performance.now() - alpeccaAiReplyStartedAt;
    if (waitingMs > ALPECCA_AI_SLOW_REPLY_MS && !alpeccaAiSlowReplyNoticeShown) {
      alpeccaAiSlowReplyNoticeShown = true;
      appendAlpeccaLog("System", "Live Alpecca is still thinking. Waiting for the core reply...");
      showAlpeccaProfileLine("Live Alpecca is still thinking. Waiting for the core reply...", "thinking");
    }
    if (waitingMs > ALPECCA_AI_PLAYER_REPLY_NOTICE_MS && !alpeccaAiExtendedReplyNoticeShown) {
      alpeccaAiExtendedReplyNoticeShown = true;
      const requestHint = alpeccaAiPendingPlayerRequestId
        ? ` Request ${alpeccaAiPendingPlayerRequestId} remains live.`
        : "";
      const noticeLine = `This reply is taking longer than usual, but Alpecca is still working on the original turn.${requestHint}`;
      appendAlpeccaLog("System", noticeLine);
      showAlpeccaProfileLine(noticeLine, "thinking");
      showMessage("Alpecca is still working on this reply.", 4);
    }
  }

  roomPanelTimer -= dt;
  updateRoomPanel();
  updateAlpeccaPresenceContext(dt);

  targetPollTimer -= dt;
  if (targetPollTimer <= 0) {
    currentTarget = alpeccaViewMode === "orthographic" ? null : getTarget();
    targetPollTimer = 0.08;
  }

  if (currentTarget) {
    promptEl.textContent = `E  ${currentTarget.label}`;
    promptEl.classList.remove("hidden");
  } else {
    promptEl.classList.add("hidden");
  }

  if (lastMessageTimer > 0) {
    lastMessageTimer -= dt;
    if (lastMessageTimer <= 0) messageEl.classList.remove("visible");
  }

  perfFrames += 1;
  perfTimer += dt;
  const qaPerf = isAlpeccaWalkQaMode() || isAlpeccaAccommodationQaMode();
  if (qaPerf && !perfAutoQaEnabled) {
    perfAutoQaEnabled = true;
    showPerf = true;
    perfEl.classList.remove("hidden");
    perfEl.textContent = "Alpecca walk QA...";
  } else if (!qaPerf && perfAutoQaEnabled) {
    perfAutoQaEnabled = false;
    showPerf = false;
    perfEl.classList.add("hidden");
  }
  if (showPerf && perfTimer >= 0.5) {
    const fps = Math.round(perfFrames / perfTimer);
    const qa = window.__ALPECCA_RUNTIME__;
    const alpeccaLine = qa
      ? ` | Alpecca ${qa.intent} ${qa.state} ${qa.direction} ${qa.flipX ? "flip" : "noflip"} ${qa.frameIndex + 1}/${qa.frameCount} ${qa.animationSourceFamily}:${qa.animationSourceStatus}${qa.animationSourceFlagged ? ":flag" : ""} rate:${qa.walkPlaybackRate} h:${qa.heightClass}${qa.standingScaleLocked ? ":locked" : ""} matrix:${qa.viewMatrix}/${qa.viewSector16Key}/${qa.matrixResolution}${qa.flipX ? ":mir" : ""} cyl:${qa.cylinderZone}/${qa.cylinderPlayerDistance}m/${qa.cylinderMovementClamped ? "clamp" : "free"} vol:${qa.viewVolumeZone}/${qa.viewVolumeProbe}/${qa.billboardClampDeg}deg asset:${qa.matrixAction}/${qa.matrixFallbackState}/${qa.matrixFrameCount}f ${qa.matrixManifestStatus} stage:${qa.stagePad} nav:${qa.navClearance} issues:${qa.stageQaIssues.length} target:${qa.perceptionTarget || "-"} ${qa.folder}`
      : "";
    perfEl.textContent = `${fps} FPS  |  ${renderer.info.render.calls} draw calls  |  ${renderer.info.render.triangles} tris${alpeccaLine}`;
    perfFrames = 0;
    perfTimer = 0;
  } else if (!showPerf && !perfEl.classList.contains("hidden")) {
    perfEl.classList.add("hidden");
    perfFrames = 0;
    perfTimer = 0;
  }
}

function stepGameFrame(dt: number) {
  dt = THREE.MathUtils.clamp(Number.isFinite(dt) ? dt : 1 / 60, 0, 0.1);
  updateKeyboardLook(dt);
  if (alpeccaViewMode === "first-person") movePlayer(dt);
  updateAlpeccaPreloadQueue(dt);
  updateAlpeccaWalkQaCycle(dt);
  updateAlpeccaVoiceEmotion(dt);
  updateAlpecca(dt);
  updateAlpeccaEmbodiment(dt);
  updateAlpeccaActivityMarkers(dt);
  updateAlpeccaRoomDevices(dt);
  updateAlpeccaDoorAwareness(dt);
  updateAlpeccaSourceTerminals(dt);
  updateAlpeccaSourceDashboard(dt);
  updateAlpeccaSourceGalleryPanels(dt);
  updateAlpeccaDetailPoints(dt);
  updateAlpeccaPerception(dt);
  updateAlpeccaMemoryTraces(dt);
  updateAlpeccaIdeaObjects(dt);
  for (const animateProp of animatedProps) animateProp(dt);
  for (const item of interactables) item.update?.(dt, item);
  updateAlpeccaHomeSystems(dt);
  updateAlpeccaExpressionProjector(dt);
  updateAlpeccaAvatarStation(dt);
  updateAlpeccaSelfMirror(dt);
  updateAlpeccaIdentityConsole(dt);
  updateAlpeccaAgiLadder(dt);
  updateAlpeccaAgiJournal(dt);
  updateAlpeccaImprovementQueue(dt);
  updateAlpeccaEnvironmentModel(dt);
  updateAlpeccaCuriosityLoop(dt);
  updateAlpeccaAutonomousWorldTick(dt);
  updateHud(dt);
  const activeCamera = alpeccaPresentationCamera();
  const sceneFog = scene.fog;
  if (alpeccaViewMode === "orthographic") scene.fog = null;
  renderer.render(scene, activeCamera);
  scene.fog = sceneFog;
  publishAlpeccaRuntimeProbe();
}

function animate() {
  stepGameFrame(Math.min(clock.getDelta(), 0.05));
}

function isAlpeccaWalkQaMode() {
  const params = new URLSearchParams(window.location.search);
  return params.has("alpecca-walk-qa") || params.has("walkQa") || params.get("qa") === "walks";
}

function isAlpeccaAccommodationQaMode() {
  const params = new URLSearchParams(window.location.search);
  return params.has("alpecca-stage-qa") || params.has("stageQa") || params.get("qa") === "stage";
}

function updateAlpeccaWalkQaCycle(dt: number) {
  if (!alpecca.ready) return;
  const enabled = isAlpeccaWalkQaMode();
  if (!enabled) {
    alpecca.walkQaTimer = 0;
    return;
  }
  if (!alpeccaChat.classList.contains("hidden")) {
    if (alpecca.showcaseState.startsWith("walk")) alpecca.showcaseTimer = 0;
    alpecca.walkQaTimer = alpeccaWalkQaInterval;
    return;
  }

  alpecca.walkQaTimer -= dt;
  if (alpecca.walkQaTimer > 0 && alpecca.showcaseTimer > 0) return;

  const nextState = alpeccaWalkQaStates[alpecca.walkQaIndex % alpeccaWalkQaStates.length];
  alpecca.walkQaIndex = (alpecca.walkQaIndex + 1) % alpeccaWalkQaStates.length;
  alpecca.walkQaTimer = alpeccaWalkQaInterval;
  showcaseAlpeccaAnimation(nextState, alpeccaWalkQaInterval);
}

window.__HOUSE_STEP__ = (dt = 1 / 60, frames = 1) => {
  const safeFrames = THREE.MathUtils.clamp(Math.floor(Number.isFinite(frames) ? frames : 1), 1, 600);
  const safeDt = THREE.MathUtils.clamp(Number.isFinite(dt) ? dt : 1 / 60, 0, 0.1);
  for (let i = 0; i < safeFrames; i += 1) stepGameFrame(safeDt);
  return window.__ALPECCA_RUNTIME__;
};

window.__ALPECCA_PLAY_ANIMATION__ = (name: AlpeccaAnimationName, seconds = 3.2) => {
  if (!isAlpeccaAnimationName(name)) return window.__ALPECCA_RUNTIME__;
  showcaseAlpeccaAnimation(name, seconds);
  return window.__ALPECCA_RUNTIME__;
};

window.__ALPECCA_LOCK_ANIMATION__ = (name: AlpeccaAnimationName, seconds = 8) => {
  if (!isAlpeccaAnimationName(name)) return window.__ALPECCA_RUNTIME__;
  showcaseAlpeccaAnimation(name, THREE.MathUtils.clamp(seconds, 0.5, 60));
  publishAlpeccaRuntimeProbe();
  return window.__ALPECCA_RUNTIME__;
};

let manualStepCount = 0;
function runManualFrameStep(detail: { dt?: number; frames?: number; alpeccaX?: number; alpeccaZ?: number; alpeccaAnimation?: AlpeccaAnimationName; alpeccaSay?: string } = {}) {
  if (alpecca.ready && Number.isFinite(detail.alpeccaX) && Number.isFinite(detail.alpeccaZ)) {
    alpecca.group.position.x = THREE.MathUtils.clamp(detail.alpeccaX!, -7.2, 7.2);
    alpecca.group.position.z = THREE.MathUtils.clamp(detail.alpeccaZ!, -5.2, 5.2);
    alpecca.routeTargetIndex = -1;
    alpecca.routeStep = 0;
    alpecca.route.length = 0;
    alpecca.stuckTimer = 0;
    alpecca.startTimer = 0;
    alpecca.walkSegmentTimer = 2.6;
    alpecca.walkPauseTimer = 0;
    clearAlpeccaTerminalInteraction();
  }
  if (alpecca.ready && detail.alpeccaAnimation) {
    showcaseAlpeccaAnimation(detail.alpeccaAnimation, 3.2);
  }
  if (alpecca.ready && detail.alpeccaSay) {
    startAlpeccaSpeech(detail.alpeccaSay);
  }
  const safeFrames = THREE.MathUtils.clamp(Math.floor(Number.isFinite(detail.frames) ? detail.frames! : 1), 1, 600);
  window.__HOUSE_STEP__?.(detail.dt, safeFrames);
  manualStepCount += safeFrames;
  document.body.dataset.houseStepCount = String(manualStepCount);
}

window.addEventListener("house-step", (event) => {
  runManualFrameStep((event as CustomEvent<{ dt?: number; frames?: number; alpeccaAnimation?: AlpeccaAnimationName; alpeccaSay?: string }>).detail ?? {});
});

window.addEventListener("message", (event) => {
  const data = event.data;
  if (!data || typeof data !== "object" || data.type !== "house-step") return;
  const requestedAnimation = typeof data.alpeccaAnimation === "string" && isAlpeccaAnimationName(data.alpeccaAnimation) ? data.alpeccaAnimation : undefined;
  runManualFrameStep({ dt: Number(data.dt), frames: Number(data.frames), alpeccaAnimation: requestedAnimation, alpeccaSay: typeof data.alpeccaSay === "string" ? data.alpeccaSay : undefined });
});

function consumeManualStepHash() {
  const params = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  const animationParam = params.get("alpecca-animation") ?? params.get("alpeccaAnimation");
  const alpeccaAnimation = animationParam && isAlpeccaAnimationName(animationParam) ? animationParam : undefined;
  const alpeccaSay = params.get("alpecca-say") ?? params.get("alpeccaSay") ?? undefined;
  if (!params.has("house-step") && !alpeccaAnimation && !alpeccaSay) return;
  runManualFrameStep({
    dt: Number(params.get("dt")) || 1 / 30,
    frames: Number(params.get("house-step")) || 1,
    alpeccaX: Number(params.get("alpecca-x") ?? params.get("alpeccaX")),
    alpeccaZ: Number(params.get("alpecca-z") ?? params.get("alpeccaZ")),
    alpeccaAnimation,
    alpeccaSay,
  });
  window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
}

window.addEventListener("hashchange", consumeManualStepHash);

function onInteract() {
  if (!currentTarget) return;
  if (currentTarget.id !== "alpecca" && !alpeccaChat.classList.contains("hidden")) closeAlpeccaChat();
  const text = currentTarget.onUse(currentTarget);
  if (text) showMessage(text);
}

function isInteractiveHudTarget(target: EventTarget | null) {
  return (
    target instanceof HTMLElement &&
    !!target.closest("button, input, textarea, select, label, .menu, .alpecca-chat, .source-panel, .systems-overlay, .move-stick, .touch-interact")
  );
}

function normalizeGameCode(event: KeyboardEvent) {
  if (event.code && event.code !== "Unidentified") return event.code;
  const key = event.key.toLowerCase();
  if (key === "w") return "KeyW";
  if (key === "a") return "KeyA";
  if (key === "s") return "KeyS";
  if (key === "d") return "KeyD";
  if (key === "e") return "KeyE";
  if (key === "f") return "KeyF";
  if (key === "arrowup") return "ArrowUp";
  if (key === "arrowdown") return "ArrowDown";
  if (key === "arrowleft") return "ArrowLeft";
  if (key === "arrowright") return "ArrowRight";
  if (key === "shift") return "ShiftLeft";
  if (key === "escape") return "Escape";
  return event.code;
}

function isGameKey(code: string) {
  return [
    "KeyW",
    "KeyA",
    "KeyS",
    "KeyD",
    "ArrowUp",
    "ArrowDown",
    "ArrowLeft",
    "ArrowRight",
    "ShiftLeft",
    "ShiftRight",
    "KeyE",
    "KeyF",
    "Escape",
  ].includes(code);
}

function handleKeyDown(event: KeyboardEvent) {
  if (event.key === "Escape") {
    event.preventDefault();
    keys.delete("Escape");
    if (!alpeccaSystems.classList.contains("hidden")) closeAlpeccaSystems();
    if (!alpeccaChat.classList.contains("hidden")) closeAlpeccaChat();
    setMenuOpen(false);
    profileQaPanel.classList.add("hidden");
    spriteQaPanel.classList.add("hidden");
    if (document.pointerLockElement) document.exitPointerLock();
    renderer.domElement.focus();
    return;
  }

  if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) {
    return;
  }

  if (!alpeccaChat.classList.contains("hidden")) {
    return;
  }

  const code = normalizeGameCode(event);
  if (alpeccaViewMode === "orthographic" && code !== "KeyF") return;
  if (isGameKey(code)) event.preventDefault();
  keys.add(code);
  if (code === "KeyE") onInteract();
  if (code === "KeyF") {
    showPerf = !showPerf;
    perfEl.classList.toggle("hidden", !showPerf);
    if (showPerf) {
      perfTimer = 0;
      perfFrames = 0;
      perfEl.textContent = "Measuring...";
    }
  }
}

function handleKeyUp(event: KeyboardEvent) {
  if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return;
  if (!alpeccaChat.classList.contains("hidden")) return;
  const code = normalizeGameCode(event);
  if (isGameKey(code)) event.preventDefault();
  keys.delete(code);
}

function applyLook(deltaX: number, deltaY: number, sensitivity = 0.0022) {
  player.yaw -= deltaX * sensitivity;
  player.pitch -= deltaY * sensitivity;
  player.pitch = THREE.MathUtils.clamp(player.pitch, -1.15, 1.15);
}

function isMouseOverCanvas(clientX: number, clientY: number) {
  const rect = renderer.domElement.getBoundingClientRect();
  const overCanvas = clientX >= rect.left && clientX <= rect.right && clientY >= rect.top && clientY <= rect.bottom;
  if (!overCanvas) edgeLook.active = false;
  return overCanvas;
}

function lockPointer() {
  if (alpeccaViewMode === "orthographic") return;
  if (document.pointerLockElement === renderer.domElement) return;
  if (!("requestPointerLock" in renderer.domElement)) {
    pointerLockBlocked = true;
    showMessage("This browser does not support mouse lock. Open the game in Chrome or Edge for locked first-person controls.", 5);
    return;
  }

  renderer.domElement.focus();
  pointerLockBlocked = false;

  const lockTarget = renderer.domElement as HTMLCanvasElement & {
    requestPointerLock: (options?: { unadjustedMovement?: boolean }) => Promise<void> | void;
  };
  const lockResult = lockTarget.requestPointerLock({ unadjustedMovement: true });
  if (lockResult instanceof Promise) {
    lockResult.catch(() => {
      const fallbackResult = lockTarget.requestPointerLock();
      if (fallbackResult instanceof Promise) fallbackResult.catch(() => undefined);
    });
  }
}

function setMenuOpen(open: boolean) {
  menu.classList.toggle("hidden", !open);
  if (open) menu.scrollTop = 0;
  else {
    profileQaPanel.classList.add("hidden");
    spriteQaPanel.classList.add("hidden");
  }
}

function updateMoveStick(clientX: number, clientY: number) {
  const rect = moveStick.getBoundingClientRect();
  const centerX = rect.left + rect.width / 2;
  const centerY = rect.top + rect.height / 2;
  const maxDistance = rect.width * 0.38;
  const dx = THREE.MathUtils.clamp(clientX - centerX, -maxDistance, maxDistance);
  const dy = THREE.MathUtils.clamp(clientY - centerY, -maxDistance, maxDistance);
  const length = Math.hypot(dx, dy);
  const scale = length > maxDistance && length > 0 ? maxDistance / length : 1;
  const stickX = dx * scale;
  const stickY = dy * scale;

  moveKnob.style.transform = `translate(calc(-50% + ${stickX}px), calc(-50% + ${stickY}px))`;
  virtualMove.x = THREE.MathUtils.clamp(stickX / maxDistance, -1, 1);
  virtualMove.z = THREE.MathUtils.clamp(stickY / maxDistance, -1, 1);
}

function resetMoveStick() {
  movePointerId = null;
  virtualMove = { x: 0, z: 0 };
  moveKnob.style.transform = "translate(-50%, -50%)";
}

updateEnvironmentModeUi();
createLighting();
createYardHint();
createPrototypeVoid();
addFurnitureOcclusion();
initializeAlpeccaAccommodationQa();
applyHudMode();
setAlpeccaViewMode(alpeccaViewMode, false);
void recoverAlpeccaEndpoint("startup", { backendStorageKey: alpeccaBackendStorageKey })
  .then((redirected) => {
    if (!redirected) void createAlpecca();
  });
showMessage(isPrototypeMode() ? "Click to enter Alpecca's void" : "Click to enter the AI Office HQ, a place in her void", 8);
connectAlpeccaAi();

const requestedSystem = urlParamValue(["system", "panel"]) as AlpeccaSystemId;
if (Object.prototype.hasOwnProperty.call(alpeccaSystemLabels, requestedSystem)) {
  window.setTimeout(() => openAlpeccaSystems(requestedSystem, false), 0);
}

renderer.setAnimationLoop(animate);

window.addEventListener("resize", () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  updateOrthographicCamera();
  renderer.setPixelRatio(targetRenderPixelRatio());
  renderer.setSize(window.innerWidth, window.innerHeight);
  applyHudMode();
});

document.addEventListener("keydown", handleKeyDown);
document.addEventListener("keyup", handleKeyUp);

hud.addEventListener(
  "pointerdown",
  (event) => {
    if (!isInteractiveHudTarget(event.target)) return;
    if (document.pointerLockElement === renderer.domElement) document.exitPointerLock();
  },
  true,
);

for (const hudEventName of ["pointerdown", "click", "touchstart"]) {
  hud.addEventListener(hudEventName, (event) => {
    if (!isInteractiveHudTarget(event.target)) return;
    event.stopPropagation();
  });
}

alpeccaChat.addEventListener("submit", (event) => {
  event.preventDefault();
  unlockAlpeccaVoicePlayback();
  const sourceRef = alpeccaPendingSourceRef;
  alpeccaPendingSourceRef = null;
  alpeccaChatInput.placeholder = "Message Alpecca...";
  void sendAlpeccaChat(alpeccaChatInput.value, "", "", sourceRef);
});

alpeccaChat.addEventListener("pointerdown", (event) => {
  event.stopPropagation();
});

alpeccaChat.addEventListener("click", (event) => {
  const target = event.target as HTMLElement;
  if (target.closest("#alpeccaPushToTalk")) {
    event.preventDefault();
    void toggleAlpeccaPushToTalk();
    return;
  }
  if (target.closest("#alpeccaCameraOpen")) {
    event.preventDefault();
    void openAlpeccaCamera();
    return;
  }
  if (target.closest("#alpeccaSpokenReplies")) {
    event.preventDefault();
    unlockAlpeccaVoicePlayback();
    toggleAlpeccaSpokenReplies();
    return;
  }
  if (target.closest("[data-camera-cancel]")) {
    event.preventDefault();
    closeAlpeccaCamera();
    alpeccaChatInput.focus();
    return;
  }
  if (target.closest("[data-camera-send]")) {
    event.preventDefault();
    void sendAlpeccaCameraFrame();
    return;
  }
  const hearVoiceButton = target.closest<HTMLButtonElement>("button[data-hear-voice]");
  if (hearVoiceButton) {
    event.preventDefault();
    unlockAlpeccaVoicePlayback();
    const currentLine = alpeccaChatLine.textContent?.trim() || "";
    const sample = currentLine && currentLine.length > 12
      ? currentLine
      : "This is my current Alpecca voice, using my original voice modulation.";
    setAlpeccaProfileMode("talking", "voice");
    showAlpeccaProfileLine("Preparing Alpecca's original voice...", "thinking", "voice");
    alpeccaBackendFetch(alpeccaUrlWithParams(`${alpeccaAiBaseUrl}/tts/warmup`), { method: "POST" })
      .catch(() => undefined)
      .finally(() => {
        showAlpeccaProfileLine("Playing Alpecca's current voice.", "talking", "voice");
        startAlpeccaSpeech(sample);
      });
    return;
  }
  const voiceButton = target.closest<HTMLButtonElement>("button[data-voice-preview]");
  if (voiceButton?.dataset.voicePreview) {
    event.preventDefault();
    unlockAlpeccaVoicePlayback();
    const preview = voiceButton.dataset.voicePreview;
    const sampleText: Record<string, string> = {
      current: "This is my current Alpecca voice state, using my F5 reference voice and original identity.",
      lively: "This is my lively modulation. Same voice, brighter motion and more spark.",
      tender: "This is my tender modulation. Same voice, softer and closer.",
      sleepy: "This is my sleepy modulation. Same voice, slower and lower energy.",
      anxious: "This is my anxious modulation. Same voice, more alert without losing myself.",
    };
    setAlpeccaProfileMode("talking", "voice");
    showAlpeccaProfileLine(`Voice QA: ${preview}`, "talking");
    startAlpeccaSpeech(sampleText[preview] || sampleText.current, preview === "current" ? "" : preview);
    return;
  }
  const featureButton = target.closest<HTMLButtonElement>("button[data-feature]");
  if (featureButton?.dataset.feature) {
    runAlpeccaFeature(featureButton.dataset.feature);
    return;
  }
  const systemButton = target.closest<HTMLButtonElement>("button[data-system-open]");
  if (systemButton?.dataset.systemOpen) {
    const systemId = systemButton.dataset.systemOpen as AlpeccaSystemId;
    appendAlpeccaLog("System", `Opening ${systemButton.textContent?.trim() || systemId}`);
    openAlpeccaSystems(systemId, true);
    return;
  }
  if (target.closest("[data-ask-room]")) {
    askAlpeccaAboutCurrentRoom();
    return;
  }
  if (target.closest("[data-world-tick]")) {
    runAlpeccaLivingLoop();
    return;
  }
  if (target.closest("[data-doctor]")) {
    runAlpeccaDoctorCheck();
    return;
  }
  if (target.closest("[data-self-review]")) {
    runAlpeccaRuntimeSelfReview();
    return;
  }
  if (target.closest("[data-review-replies]")) {
    reviewAlpeccaReplies();
    return;
  }
  if (target.closest("[data-improvement-queue]")) {
    openAlpeccaWorkshop();
    return;
  }
  if (target.closest("[data-open-systems]")) openAlpeccaTerminal(true);
});

// The Workshop overlay owns its own clicks: the backdrop and close button
// dismiss it, the header buttons run review / compact / refresh, and each card's
// controls move that one proposal through its bounded lifecycle.
alpeccaWorkshop.addEventListener("pointerdown", (event) => {
  event.stopPropagation();
});

alpeccaWorkshop.addEventListener("click", (event) => {
  const target = event.target as HTMLElement;
  if (target === alpeccaWorkshop || target.closest("[data-workshop-close]")) {
    closeAlpeccaWorkshop();
    return;
  }
  if (target.closest("[data-workshop-run]")) {
    void workshopRunReview();
    return;
  }
  if (target.closest("[data-workshop-compact]")) {
    void workshopCompact();
    return;
  }
  if (target.closest("[data-workshop-handoff]")) {
    void workshopExportHandoff();
    return;
  }
  if (target.closest("[data-workshop-refresh]")) {
    void loadAlpeccaWorkshop();
    void loadWorkshopTrialStatus();
    return;
  }
  const reviewButton = target.closest<HTMLButtonElement>("button[data-wc-review-act]");
  if (
    reviewButton?.dataset.wcReviewAct === "retain-trial-value"
    || reviewButton?.dataset.wcReviewAct === "revert-to-baseline"
  ) {
    const trialId = Number(reviewButton.dataset.wcReviewTrialId || 0);
    void workshopReviewDecisionAction(trialId, reviewButton.dataset.wcReviewAct);
    return;
  }
  const trialButton = target.closest<HTMLButtonElement>("button[data-wc-trial-act]");
  if (trialButton?.dataset.wcTrialAct) {
    const proposalId = Number(trialButton.dataset.wcId || 0);
    const trialId = Number(trialButton.dataset.wcTrialId || 0);
    void workshopBehaviorTrialAction(proposalId, trialButton.dataset.wcTrialAct, trialId);
    return;
  }
  const actButton = target.closest<HTMLButtonElement>("button[data-wc-act]");
  if (actButton?.dataset.wcAct) {
    const proposalId = Number(actButton.dataset.wcId || 0);
    void workshopProposalDecision(proposalId, actButton.dataset.wcAct);
  }
});

async function postAlpeccaSystem(
  path: string,
  body?: Record<string, unknown>,
  lease: AlpeccaCapabilityLease | null = null,
) {
  if (!alpeccaAiBaseUrl) throw new Error("Live backend URL missing");
  const initialHeaders = body ? { "Content-Type": "application/json" } : undefined;
  const response = await alpeccaBackendFetch(alpeccaUrlWithParams(`${alpeccaAiBaseUrl}${path}`), {
    method: "POST",
    headers: lease ? alpeccaCapabilityLeaseHeaders(lease, initialHeaders) : initialHeaders,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  return await response.json() as Record<string, unknown>;
}

async function revokeAlpeccaPushEndpoint(endpoint: string) {
  if (!alpeccaAiBaseUrl) throw new Error("Live backend URL missing");
  const path = "/notifications/push/subscription";
  const response = await alpeccaBackendFetch(alpeccaUrlWithParams(`${alpeccaAiBaseUrl}${path}`), {
    method: "DELETE",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ endpoint }),
  });
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
}

async function removeAlpeccaPushSubscription(
  registration: ServiceWorkerRegistration,
  subscription: PushSubscription,
) {
  await subscription.unsubscribe();
  const remaining = await registration.pushManager.getSubscription();
  if (remaining?.endpoint === subscription.endpoint) {
    throw new Error("The browser could not remove its previous push subscription.");
  }
}

async function enableAlpeccaPushNotifications() {
  if (!alpeccaPushBrowserSupported()) {
    throw new Error("Web Push requires a supported browser and secure House HQ connection.");
  }
  if (!alpeccaPushBackendIsSameOrigin()) {
    throw new Error("Creator alerts require House HQ and the backend on the same origin.");
  }
  const permission = Notification.permission === "granted"
    ? "granted"
    : await Notification.requestPermission();
  if (permission !== "granted") throw new Error("Notification permission was not granted.");

  const status = await fetchAlpeccaPushStatus();
  if (!alpeccaPushServerReady(status)) {
    throw new Error(systemString(status.reason || status.status, "The notification transport is unavailable."));
  }
  const applicationServerKey = decodeAlpeccaPushApplicationServerKey(
    alpeccaPushApplicationServerKey(status),
  );
  const registration = await registerAlpeccaServiceWorker();
  if (!registration) throw new Error("The House HQ service worker is unavailable.");

  let subscription = await registration.pushManager.getSubscription();
  if (subscription && !alpeccaPushSubscriptionUsesKey(subscription, applicationServerKey)) {
    await revokeAlpeccaPushEndpoint(subscription.endpoint);
    await removeAlpeccaPushSubscription(registration, subscription);
    subscription = null;
  }
  let created = false;
  if (!subscription) {
    subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey,
    });
    created = true;
  }
  try {
    await postAlpeccaSystem("/notifications/push/subscription", { subscription: subscription.toJSON() });
  } catch (error) {
    if (created) await removeAlpeccaPushSubscription(registration, subscription).catch(() => {});
    throw error;
  }
  return "Creator alerts are enabled in this browser.";
}

async function disableAlpeccaPushNotifications() {
  if (!alpeccaPushBackendIsSameOrigin()) {
    throw new Error("Creator alerts require House HQ and the backend on the same origin.");
  }
  const registration = await registerAlpeccaServiceWorker();
  const subscription = await registration?.pushManager.getSubscription();
  if (!subscription) return "Creator alerts are already disabled in this browser.";
  await revokeAlpeccaPushEndpoint(subscription.endpoint);
  await removeAlpeccaPushSubscription(registration!, subscription);
  return "Creator alerts are disabled in this browser.";
}

async function testAlpeccaPushNotifications() {
  if (!alpeccaPushBrowserSupported() || Notification.permission !== "granted") {
    throw new Error("Enable creator alerts in this browser before sending a test.");
  }
  if (!alpeccaPushBackendIsSameOrigin()) {
    throw new Error("Creator alerts require House HQ and the backend on the same origin.");
  }
  const status = await fetchAlpeccaPushStatus();
  const applicationServerKey = decodeAlpeccaPushApplicationServerKey(
    alpeccaPushApplicationServerKey(status),
  );
  const subscription = await currentAlpeccaPushSubscription();
  if (!subscription || !alpeccaPushSubscriptionUsesKey(subscription, applicationServerKey)) {
    throw new Error("Enable creator alerts in this browser before sending a test.");
  }
  const result = await postAlpeccaSystem("/notifications/push/test", {});
  const delivery = systemRecord(result.delivery);
  const accepted = Math.max(0, Number(delivery.accepted) || 0);
  const rejected = Math.max(0, Number(delivery.rejected) || 0);
  const unknown = Math.max(0, Number(delivery.unknown) || 0);
  const undispatched = Math.max(0, Number(delivery.undispatched) || 0);
  if (
    delivery.attempted === true
    && delivery.state === "sent"
    && accepted >= 1
    && rejected === 0
    && unknown === 0
    && undispatched === 0
  ) {
    return "The test alert was accepted by this browser's push provider.";
  }
  if (result.in_progress === true) {
    throw new Error("The test alert is still in progress. Check outbox status before retrying.");
  }
  const reason = systemString(
    result.reason,
    unknown > 0
      ? "The push provider outcome is unknown. Do not retry until outbox status is resolved."
      : "The test alert was not accepted.",
  );
  throw new Error(reason);
}

function setAlpeccaSystemResults(html: string) {
  const results = alpeccaSystemsBody.querySelector<HTMLDivElement>("#alpeccaSystemResults");
  if (results) results.innerHTML = html;
}

async function searchAlpeccaSystem(kind: "memory" | "files") {
  const input = alpeccaSystemsBody.querySelector<HTMLInputElement>(kind === "memory" ? "#alpeccaMemoryQuery" : "#alpeccaFileQuery");
  const query = input?.value.trim() || "";
  if (!query || !alpeccaAiBaseUrl) return;
  setAlpeccaSystemsNotice(`Searching ${kind}...`);
  try {
    const path = kind === "memory" ? "/memories/search" : "/desktop/search";
    const url = alpeccaUrlWithParams(`${alpeccaAiBaseUrl}${path}`, { q: query, limit: kind === "memory" ? "12" : "40" });
    const response = await alpeccaBackendFetch(url);
    if (!response.ok) throw new Error(`search returned ${response.status}`);
    const data = await response.json() as Record<string, unknown>;
    const items = systemArray(data.matches || data.results || data.items || data.files);
    setAlpeccaSystemResults(`<section><h3>Search results</h3>${items.map((item) => {
      const title = systemString(item.kind || item.name || item.root, kind === "memory" ? "memory" : "file");
      const detail = systemString(item.content || item.body || item.path || item.rel || item.name);
      if (kind === "files") {
        const root = systemString(item.root, "");
        const rel = systemString(item.rel, "");
        const kindLabel = systemString(item.kind || item.type, "").toLowerCase();
        const isDirectory = item.is_dir === true || kindLabel === "directory" || kindLabel === "folder";
        if (!isDirectory && root && rel && isAlpeccaAttachableTextFile(rel)) {
          const encodedRoot = escapeHudText(encodeURIComponent(root));
          const encodedRel = escapeHudText(encodeURIComponent(rel));
          return `<div class="systems-row systems-game"><span class="systems-badge">${escapeHudText(root)}</span><div><strong>${escapeHudText(title)}</strong><p>${escapeHudText(detail)}</p></div><div><button type="button" data-file-attach data-file-root="${encodedRoot}" data-file-rel="${encodedRel}" aria-label="Attach ${escapeHudText(title)}">Attach</button></div></div>`;
        }
      }
      return systemRow(title, detail, systemString(item.recall_method || item.root, ""));
    }).join("") || systemEmpty("No matching result.")}</section>`);
    setAlpeccaSystemsNotice("");
  } catch (error) {
    setAlpeccaSystemsNotice(error instanceof Error ? error.message : "Search unavailable");
  }
}

async function pushAlpeccaScreenFrame(sequence: number, lease: AlpeccaCapabilityLease) {
  const video = alpeccaScreenShareVideo;
  if (
    sequence !== alpeccaScreenShareSequence
    || alpeccaScreenShareRequest
    || !video
    || !alpeccaAiBaseUrl
    || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA
    || !video.videoWidth
  ) return;
  const scale = Math.min(1, 960 / video.videoWidth);
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
  canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
  canvas.getContext("2d")?.drawImage(video, 0, 0, canvas.width, canvas.height);
  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.72));
  if (!blob || sequence !== alpeccaScreenShareSequence) return;
  const request = new AbortController();
  alpeccaScreenShareRequest = request;
  try {
    const response = await alpeccaBackendFetch(alpeccaUrlWithParams(`${alpeccaAiBaseUrl}/sight/push`), {
      method: "POST",
      headers: alpeccaCapabilityLeaseHeaders(lease, { "Content-Type": "image/jpeg" }),
      body: blob,
      signal: request.signal,
    });
    if (!response.ok) throw new Error(`screen sight returned ${response.status}`);
  } finally {
    if (alpeccaScreenShareRequest === request) alpeccaScreenShareRequest = null;
  }
}

async function stopAlpeccaScreenShare(options: {
  notifyBackend?: boolean;
  stopLease?: boolean;
  notice?: boolean;
} = {}) {
  const { notifyBackend = true, stopLease = true, notice = true } = options;
  alpeccaScreenShareSequence += 1;
  if (alpeccaScreenShareTimer !== null) window.clearInterval(alpeccaScreenShareTimer);
  alpeccaScreenShareTimer = null;
  alpeccaScreenShareRequest?.abort();
  alpeccaScreenShareRequest = null;
  const stream = alpeccaScreenShareStream;
  alpeccaScreenShareStream = null;
  alpeccaScreenShareVideo = null;
  stream?.getTracks().forEach((track) => {
    track.onended = null;
    track.stop();
  });
  if (notifyBackend && alpeccaAiBaseUrl) {
    try {
      await postAlpeccaSystem("/observatory/screen/stop");
    } catch {}
  }
  if (stopLease) await stopAlpeccaCapabilityLease("screen_share");
  if (notice) setAlpeccaSystemsNotice("Screen sharing stopped.");
  if (alpeccaActiveSystem === "senses" || alpeccaActiveSystem === "observatory") void loadAlpeccaSystem(alpeccaActiveSystem);
}

async function startAlpeccaScreenShare() {
  if (!navigator.mediaDevices?.getDisplayMedia) {
    setAlpeccaSystemsNotice("This browser does not provide screen sharing.");
    return;
  }
  await stopAlpeccaScreenShare({ notifyBackend: false, stopLease: true, notice: false });
  if (alpeccaSystems.classList.contains("hidden")) return;
  const sequence = ++alpeccaScreenShareSequence;
  let lease: AlpeccaCapabilityLease | null = null;
  let backendStarted = false;
  try {
    lease = await acquireAlpeccaCapabilityLease("screen_share");
    const screenLease = lease;
    if (sequence !== alpeccaScreenShareSequence) {
      await stopAlpeccaCapabilityLease(screenLease);
      return;
    }
    const stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
    if (sequence !== alpeccaScreenShareSequence) {
      stream.getTracks().forEach((track) => track.stop());
      await stopAlpeccaCapabilityLease(screenLease);
      return;
    }
    const video = document.createElement("video");
    video.muted = true;
    video.playsInline = true;
    video.srcObject = stream;
    alpeccaScreenShareStream = stream;
    alpeccaScreenShareVideo = video;
    stream.getVideoTracks()[0].onended = () => {
      if (alpeccaScreenShareStream === stream) void stopAlpeccaScreenShare();
    };
    await video.play();
    if (sequence !== alpeccaScreenShareSequence) return;
    await postAlpeccaSystem("/observatory/screen/start", undefined, screenLease);
    backendStarted = true;
    if (sequence !== alpeccaScreenShareSequence) {
      try {
        await postAlpeccaSystem("/observatory/screen/stop");
      } catch {}
      return;
    }
    await pushAlpeccaScreenFrame(sequence, screenLease);
    if (sequence !== alpeccaScreenShareSequence) return;
    alpeccaScreenShareTimer = window.setInterval(() => {
      void pushAlpeccaScreenFrame(sequence, screenLease).catch(async () => {
        if (sequence !== alpeccaScreenShareSequence) return;
        await stopAlpeccaScreenShare();
        setAlpeccaSystemsNotice("Screen sharing stopped because permission expired or a frame failed.");
      });
    }, 10000);
    setAlpeccaSystemsNotice("Screen sharing is active. Alpecca receives throttled descriptions, not stored frames.");
  } catch (error) {
    if (sequence !== alpeccaScreenShareSequence) {
      if (lease) await stopAlpeccaCapabilityLease(lease);
      return;
    }
    await stopAlpeccaScreenShare({ notifyBackend: backendStarted, stopLease: true, notice: false });
    setAlpeccaSystemsNotice(error instanceof Error ? error.message : "Screen sharing was not started.");
  }
}

async function cancelAlpeccaVoiceEnrollment(stopLease = true) {
  alpeccaVoiceEnrollmentSequence += 1;
  if (alpeccaVoiceEnrollmentTimer !== null) window.clearTimeout(alpeccaVoiceEnrollmentTimer);
  alpeccaVoiceEnrollmentTimer = null;
  alpeccaVoiceEnrollmentRequest?.abort();
  alpeccaVoiceEnrollmentRequest = null;
  const recorder = alpeccaVoiceEnrollmentRecorder;
  alpeccaVoiceEnrollmentRecorder = null;
  if (recorder && recorder.state !== "inactive") {
    try {
      recorder.stop();
    } catch {}
  }
  const stream = alpeccaVoiceEnrollmentStream;
  alpeccaVoiceEnrollmentStream = null;
  stream?.getTracks().forEach((track) => {
    track.onended = null;
    track.stop();
  });
  if (stopLease) await stopAlpeccaCapabilityLease("voice_enrollment");
}

async function enrollAlpeccaCreatorVoice() {
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
    setAlpeccaSystemsNotice("Voice enrollment is not available in this browser.");
    return;
  }
  await cancelAlpeccaPushToTalk();
  await cancelAlpeccaVoiceEnrollment();
  if (alpeccaSystems.classList.contains("hidden")) return;
  const sequence = ++alpeccaVoiceEnrollmentSequence;
  let lease: AlpeccaCapabilityLease | null = null;
  let stream: MediaStream | null = null;
  let recorder: MediaRecorder | null = null;
  setAlpeccaSystemsNotice("Requesting microphone permission...");
  try {
    lease = await acquireAlpeccaCapabilityLease("voice_enrollment");
    if (sequence !== alpeccaVoiceEnrollmentSequence) {
      await stopAlpeccaCapabilityLease(lease);
      return;
    }
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    if (sequence !== alpeccaVoiceEnrollmentSequence) {
      stream.getTracks().forEach((track) => track.stop());
      await stopAlpeccaCapabilityLease(lease);
      return;
    }
    alpeccaVoiceEnrollmentStream = stream;
    stream.getAudioTracks().forEach((track) => {
      track.onended = () => {
        if (alpeccaVoiceEnrollmentStream === stream) void cancelAlpeccaVoiceEnrollment();
      };
    });
    recorder = new MediaRecorder(stream);
    alpeccaVoiceEnrollmentRecorder = recorder;
    const chunks: Blob[] = [];
    const mimeType = recorder.mimeType || "audio/webm";
    const audio = await new Promise<Blob>((resolve, reject) => {
      recorder!.ondataavailable = (event) => {
        if (event.data.size) chunks.push(event.data);
      };
      recorder!.onerror = () => reject(new Error("Voice recording stopped unexpectedly."));
      recorder!.onstop = () => resolve(new Blob(chunks, { type: mimeType }));
      recorder!.start();
      const timer = window.setTimeout(() => {
        if (alpeccaVoiceEnrollmentTimer !== timer) return;
        alpeccaVoiceEnrollmentTimer = null;
        if (sequence === alpeccaVoiceEnrollmentSequence && recorder?.state === "recording") recorder.stop();
      }, 5000);
      alpeccaVoiceEnrollmentTimer = timer;
    });
    if (sequence !== alpeccaVoiceEnrollmentSequence) return;
    if (alpeccaVoiceEnrollmentTimer !== null) window.clearTimeout(alpeccaVoiceEnrollmentTimer);
    alpeccaVoiceEnrollmentTimer = null;
    alpeccaVoiceEnrollmentRecorder = null;
    recorder.ondataavailable = null;
    recorder.onstop = null;
    recorder.onerror = null;
    stream.getTracks().forEach((track) => {
      track.onended = null;
      track.stop();
    });
    alpeccaVoiceEnrollmentStream = null;
    setAlpeccaSystemsNotice("Creating the local creator voice embedding...");
    const request = new AbortController();
    alpeccaVoiceEnrollmentRequest = request;
    const response = await alpeccaBackendFetch(alpeccaUrlWithParams(`${alpeccaAiBaseUrl}/people/enroll_voice`), {
      method: "POST",
      headers: alpeccaCapabilityLeaseHeaders(lease, { "Content-Type": mimeType }),
      body: audio,
      signal: request.signal,
    });
    if (!response.ok) throw new Error(`voice enrollment returned ${response.status}`);
    const data = await response.json() as Record<string, unknown>;
    if (sequence !== alpeccaVoiceEnrollmentSequence) return;
    setAlpeccaSystemsNotice(data.ok ? "Creator voice enrolled locally." : "The voice embedding backend is unavailable.");
  } catch (error) {
    if (sequence === alpeccaVoiceEnrollmentSequence) {
      const detail = error instanceof Error && /^(Live House|Voice enrollment)/.test(error.message)
        ? error.message
        : "Voice enrollment failed or microphone access was denied.";
      setAlpeccaSystemsNotice(detail);
    }
  } finally {
    if (alpeccaVoiceEnrollmentTimer !== null && sequence === alpeccaVoiceEnrollmentSequence) {
      window.clearTimeout(alpeccaVoiceEnrollmentTimer);
      alpeccaVoiceEnrollmentTimer = null;
    }
    if (alpeccaVoiceEnrollmentRequest && sequence === alpeccaVoiceEnrollmentSequence) {
      alpeccaVoiceEnrollmentRequest = null;
    }
    if (alpeccaVoiceEnrollmentRecorder === recorder) alpeccaVoiceEnrollmentRecorder = null;
    if (alpeccaVoiceEnrollmentStream === stream) alpeccaVoiceEnrollmentStream = null;
    if (recorder) {
      recorder.ondataavailable = null;
      recorder.onstop = null;
      recorder.onerror = null;
      if (recorder.state !== "inactive") {
        try {
          recorder.stop();
        } catch {}
      }
    }
    stream?.getTracks().forEach((track) => {
      track.onended = null;
      track.stop();
    });
    if (lease) await stopAlpeccaCapabilityLease(lease);
  }
}

async function handleAlpeccaSystemAction(action: string) {
  setAlpeccaSystemsNotice("");
  try {
    if (action === "memory-search") return void searchAlpeccaSystem("memory");
    if (action === "file-search") return void searchAlpeccaSystem("files");
    if (action === "screen-start") return void startAlpeccaScreenShare();
    if (action === "screen-stop") return void stopAlpeccaScreenShare();
    if (action === "enroll-voice") return void enrollAlpeccaCreatorVoice();
    if (action === "push-enable" || action === "push-disable" || action === "push-test") {
      if (alpeccaPushActionPending) return;
      alpeccaPushActionPending = true;
      try {
        const message = action === "push-enable"
          ? await enableAlpeccaPushNotifications()
          : action === "push-disable"
            ? await disableAlpeccaPushNotifications()
            : await testAlpeccaPushNotifications();
        await loadAlpeccaSystem("devices");
        setAlpeccaSystemsNotice(message);
      } finally {
        alpeccaPushActionPending = false;
      }
      return;
    }
    if (action === "voice-preview") {
      alpeccaVoiceLastText = "";
      startAlpeccaSpeech("This is my current voice, grounded in how I feel right now.", "", "preview");
      return;
    }
    if (action === "device-page" || action === "classic-chat") {
      const path = action === "device-page" ? "/app" : "/classic";
      window.open(alpeccaUrlWithParams(`${alpeccaAiBaseUrl}${path}`), "_blank", "noopener,noreferrer");
      return;
    }
    if (action === "open-workshop") {
      closeAlpeccaSystems();
      openAlpeccaWorkshop();
      return;
    }
    if (action === "run-review") {
      await postAlpeccaSystem("/cognition/self-review");
      setAlpeccaSystemsNotice("Runtime self-review added grounded evidence to the queue.");
      await loadAlpeccaSystem("growth");
      return;
    }
    if (action === "propose-status") {
      await postAlpeccaSystem("/commitments", { tool: "self_status", args: {} });
      await loadAlpeccaSystem("growth");
      return;
    }
    if (action === "studio-work") {
      const data = await postAlpeccaSystem("/studio/work");
      setAlpeccaSystemsNotice(data.started ? "Alpecca started one bounded studio work unit." : systemString(data.error, "Studio is busy."));
      return;
    }
    if (action === "watch") {
      const input = alpeccaSystemsBody.querySelector<HTMLInputElement>("#alpeccaWatchUrl");
      const url = input?.value.trim() || "";
      if (!url.startsWith("https://")) throw new Error("A secure https URL is required.");
      const title = new URL(url).hostname;
      await postAlpeccaSystem("/observatory/watch", { title, url });
      await loadAlpeccaSystem("observatory");
      return;
    }
    if (action === "watch-react") {
      await postAlpeccaSystem("/observatory/react", {});
      await loadAlpeccaSystem("observatory");
      return;
    }
    if (action === "doctor") {
      const response = await alpeccaBackendFetch(alpeccaUrlWithParams(`${alpeccaAiBaseUrl}/system/doctor`));
      if (!response.ok) throw new Error(`doctor returned ${response.status}`);
      const data = await response.json() as Record<string, unknown>;
      alpeccaSystemsBody.innerHTML = `${systemIntro("DOCTOR", "Diagnostic report", "A live, grounded check of Alpecca's active layers.")}<section><h3>Findings</h3>${systemObjectRows(data, 30)}</section>`;
      alpeccaSystemsStatus.textContent = "Runtime doctor complete";
    }
  } catch (error) {
    setAlpeccaSystemsNotice(error instanceof Error ? error.message : "Action failed.");
  }
}

alpeccaSystems.addEventListener("pointerdown", (event) => {
  event.stopPropagation();
});

alpeccaSystems.addEventListener("click", (event) => {
  const target = event.target as HTMLElement;
  if (target === alpeccaSystems || target.closest("[data-systems-close]")) {
    closeAlpeccaSystems();
    return;
  }
  if (target.closest("[data-systems-refresh]")) {
    void loadAlpeccaSystem();
    return;
  }
  const systemButton = target.closest<HTMLButtonElement>("button[data-system-id]");
  if (systemButton?.dataset.systemId) {
    void loadAlpeccaSystem(systemButton.dataset.systemId as AlpeccaSystemId);
    return;
  }
  const driveModeButton = target.closest<HTMLButtonElement>("button[data-drive-mode]");
  if (driveModeButton?.dataset.driveMode) {
    alpeccaDriveMode = driveModeButton.dataset.driveMode as DesktopPanelMode;
    void loadAlpeccaSystem("files");
    return;
  }
  const actionButton = target.closest<HTMLButtonElement>("button[data-system-action]");
  if (actionButton?.dataset.systemAction) {
    void handleAlpeccaSystemAction(actionButton.dataset.systemAction);
    return;
  }
  const fileAttachButton = target.closest<HTMLButtonElement>("button[data-file-attach]");
  if (fileAttachButton) {
    let root = "";
    let rel = "";
    try {
      root = decodeURIComponent(fileAttachButton.dataset.fileRoot || "");
      rel = decodeURIComponent(fileAttachButton.dataset.fileRel || "");
    } catch {
      setAlpeccaSystemsNotice("That file reference could not be selected.");
      return;
    }
    if (!root || !rel) {
      setAlpeccaSystemsNotice("That file reference is incomplete.");
      return;
    }
    prepareAlpeccaFileAttachment({ root, rel });
    return;
  }
  const commitmentButton = target.closest<HTMLButtonElement>("button[data-commitment-action]");
  if (commitmentButton?.dataset.commitmentAction) {
    const commitmentId = Number(commitmentButton.dataset.commitmentId || 0);
    if (!Number.isInteger(commitmentId) || commitmentId <= 0) return;
    const action = commitmentButton.dataset.commitmentAction;
    const path = `/commitments/${commitmentId}/${action === "approve" ? "approve" : "execute"}`;
    void postAlpeccaSystem(path)
      .then(async (data) => {
        const status = systemString(
          (data.commitment as Record<string, unknown> | undefined)?.state ||
            (data.execution as Record<string, unknown> | undefined)?.status,
          action === "approve" ? "approved" : "finished",
        );
        setAlpeccaSystemsNotice(`Commitment ${commitmentId}: ${status}.`);
        await loadAlpeccaSystem("growth");
      })
      .catch((error) => setAlpeccaSystemsNotice(error instanceof Error ? error.message : "Commitment action failed."));
    return;
  }
  const gameButton = target.closest<HTMLButtonElement>("button[data-game-open], button[data-game-alpecca]");
  if (gameButton) {
    const encoded = gameButton.dataset.gameOpen || gameButton.dataset.gameAlpecca || "";
    const url = decodeURIComponent(encoded);
    if (!url.startsWith("https://")) return;
    if (gameButton.dataset.gameOpen) window.open(url, "_blank", "noopener,noreferrer");
    else void postAlpeccaSystem("/games/play", { url })
      .then((data) => setAlpeccaSystemsNotice(systemString(data.result, data.ok ? "Game opened." : "Game actuator unavailable.")))
      .catch((error) => setAlpeccaSystemsNotice(error instanceof Error ? error.message : "Game could not be opened."));
  }
});

alpeccaSystems.addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  const target = event.target as HTMLElement;
  if (target.id === "alpeccaMemoryQuery") {
    event.preventDefault();
    void searchAlpeccaSystem("memory");
  } else if (target.id === "alpeccaFileQuery") {
    event.preventDefault();
    void searchAlpeccaSystem("files");
  } else if (target.id === "alpeccaWatchUrl") {
    event.preventDefault();
    void handleAlpeccaSystemAction("watch");
  }
});

alpeccaSourcePanel.addEventListener("pointerdown", (event) => {
  event.stopPropagation();
});

alpeccaSourcePanel.addEventListener("click", (event) => {
  const navButton = (event.target as HTMLElement).closest<HTMLButtonElement>("button[data-nav]");
  if (navButton?.dataset.nav) {
    runAlpeccaSourceNav(navButton.dataset.nav);
    return;
  }
  const button = (event.target as HTMLElement).closest<HTMLButtonElement>("button[data-feature]");
  if (!button?.dataset.feature) return;
  runAlpeccaFeature(button.dataset.feature);
});

// Every source-panel destination opens IN her own systems overlay (same app,
// no new window): each id maps to a section that fetches its backend endpoint
// and renders in-place. "tools" maps to her Soul deliberation surface.
function runAlpeccaSourceNav(nav: string) {
  const section: AlpeccaSystemId =
    nav === "mindscape" ? "mindscape"
    : nav === "voice" ? "voice"
    : nav === "journal" ? "journal"
    : nav === "tools" ? "soul"
    : "overview";
  openAlpeccaSystems(section, true);
}

openAlpeccaSourceButton.addEventListener("click", () => {
  openAlpeccaTerminal(true);
});

viewModeToggle.addEventListener("click", (event) => {
  event.stopPropagation();
  setAlpeccaViewMode(alpeccaViewMode === "orthographic" ? "first-person" : "orthographic");
  setMenuOpen(false);
});

calmModeToggle.addEventListener("click", (event) => {
  event.stopPropagation();
  alpeccaAppMemory.visualCalmMode = !alpeccaAppMemory.visualCalmMode;
  saveAlpeccaAppMemory();
  updateCoreStatusLabels();
  appendAlpeccaLog("System", `Calm mode ${alpeccaAppMemory.visualCalmMode ? "enabled" : "disabled"}`);
});

hudModeToggle.addEventListener("click", (event) => {
  event.stopPropagation();
  alpeccaAppMemory.hudMode =
    alpeccaAppMemory.hudMode === "auto" ? "minimal" : alpeccaAppMemory.hudMode === "minimal" ? "full" : "auto";
  saveAlpeccaAppMemory();
  applyHudMode();
  updateCoreStatusLabels();
  appendAlpeccaLog("System", `HUD mode: ${alpeccaAppMemory.hudMode}`);
});

embodimentToggle.addEventListener("click", (event) => {
  event.stopPropagation();
  if (alpeccaEmbodimentState === "loading") return;
  if (isAlpeccaVrm3D()) {
    deactivateAlpeccaVrm();
    appendAlpeccaLog("System", "Alpecca returned to her 2D sprite body.");
    return;
  }
  void activateAlpeccaVrm();
});

hudChipsEl.addEventListener("pointerdown", (event) => {
  event.stopPropagation();
});

hudChipsEl.addEventListener("click", (event) => {
  event.stopPropagation();
  const chip = (event.target as HTMLElement).closest<HTMLButtonElement>("button[data-expands]");
  if (!chip?.dataset.expands) return;
  toggleHudCard(chip.dataset.expands, chip);
});

sourceChip.addEventListener("pointerdown", (event) => {
  event.stopPropagation();
});

sourceChip.addEventListener("click", (event) => {
  event.stopPropagation();
  toggleHudCard("sourcePanel", sourceChip);
});

document.addEventListener("pointerdown", (event) => {
  if (!hudExpandedCard) return;
  const target = event.target as HTMLElement | null;
  if (target?.closest(".hud-expanded, .hud-chips, .source-chip")) return;
  collapseHudCards();
});

profileQaToggle.addEventListener("click", (event) => {
  event.stopPropagation();
  profileQaPanel.classList.toggle("hidden");
});

spriteQaToggle.addEventListener("click", (event) => {
  event.stopPropagation();
  spriteQaPanel.classList.toggle("hidden");
});

stageQaToggle.addEventListener("click", (event) => {
  event.stopPropagation();
  const visible = !(alpeccaStageQaGroup?.visible ?? false);
  setAlpeccaStageQaVisible(visible);
  appendAlpeccaLog("System", `Stage QA ${visible ? "visible" : "hidden"}`);
});

cylinderQaToggle.addEventListener("click", (event) => {
  event.stopPropagation();
  const visible = !isAlpeccaCylinderQaMode();
  setAlpeccaCylinderQaVisible(visible);
  appendAlpeccaLog("System", `Cylinder QA ${visible ? "visible" : "hidden"}`);
});

profileQaPanel.addEventListener("click", (event) => {
  event.stopPropagation();
  const button = (event.target as HTMLElement).closest<HTMLButtonElement>("button");
  if (!button) return;
  let qaLabel = "";
  if (button.dataset.profileMood) {
    alpeccaAiMood = button.dataset.profileMood;
    updateCoreStatusLabels();
    qaLabel = `mood ${button.dataset.profileMood}`;
  }
  if (button.dataset.profileMode) {
    setAlpeccaProfileMode(button.dataset.profileMode, alpeccaActiveProfileFeature);
    qaLabel = `mode ${button.dataset.profileMode}`;
  }
  if (qaLabel) showAlpeccaProfileLine(`Profile QA: ${qaLabel}`, button.dataset.profileMode || alpeccaProfileMode);
});

spriteQaPanel.addEventListener("click", (event) => {
  event.stopPropagation();
  const button = (event.target as HTMLElement).closest<HTMLButtonElement>("button[data-sprite-state]");
  const state = button?.dataset.spriteState as AlpeccaAnimationName | undefined;
  if (!state || !(state in alpeccaAnimationConfig)) return;
  showcaseAlpeccaAnimation(state, 3.2);
  appendAlpeccaLog("System", `Sprite QA: ${state}`);
  showPerf = true;
  perfEl.classList.remove("hidden");
});

chatClose.addEventListener("click", (event) => {
  event.preventDefault();
  event.stopPropagation();
  closeAlpeccaChat();
});

alpeccaBackendInput.addEventListener("input", () => {
  const normalized = normalizeAlpeccaBackendUrl(alpeccaBackendInput.value);
  if (normalized) localStorage.setItem(alpeccaBackendStorageKey, normalized);
});

alpeccaBackendInput.addEventListener("change", () => {
  const normalized = normalizeAlpeccaBackendUrl(alpeccaBackendInput.value);
  if (!normalized) {
    localStorage.removeItem(alpeccaBackendStorageKey);
    alpeccaBackendInput.value = "";
    return;
  }
  localStorage.setItem(alpeccaBackendStorageKey, normalized);
  alpeccaBackendInput.value = normalized;
  window.location.reload();
});

alpeccaBackendInput.addEventListener("pointerdown", (event) => {
  event.stopPropagation();
});

window.addEventListener("mousemove", (event) => {
  if (alpeccaViewMode === "orthographic") return;
  const overCanvas = isMouseOverCanvas(event.clientX, event.clientY);
  if (document.pointerLockElement === renderer.domElement) {
    applyLook(event.movementX, event.movementY);
    return;
  }

  if (overCanvas) {
    const deltaX = event.movementX || (lastMouse ? event.clientX - lastMouse.x : 0);
    const deltaY = event.movementY || (lastMouse ? event.clientY - lastMouse.y : 0);
    if (lastMouse || isDraggingLook) applyLook(deltaX, deltaY, isDraggingLook ? 0.003 : 0.0028);
    lastMouse = { x: event.clientX, y: event.clientY };
  }
});

window.addEventListener("mouseup", () => {
  isDraggingLook = false;
  lastMouse = null;
});

window.addEventListener("blur", () => {
  isDraggingLook = false;
  lastMouse = null;
  edgeLook.active = false;
  lastTouch = null;
  keys.clear();
  resetMoveStick();
});

renderer.domElement.addEventListener("click", () => {
  renderer.domElement.focus();
  lockPointer();
});

renderer.domElement.addEventListener("mousedown", (event) => {
  if (event.button !== 0) return;
  if (alpeccaViewMode === "orthographic") return;
  event.preventDefault();
  renderer.domElement.focus();
  lockPointer();
  isDraggingLook = true;
  lastMouse = { x: event.clientX, y: event.clientY };
  renderer.domElement.focus();
  if (!pointerLockBlocked) showMessage("Mouse locked. Press Esc to release.", 2.4);
});

renderer.domElement.addEventListener("mouseleave", () => {
  isDraggingLook = false;
  lastMouse = null;
  edgeLook.active = false;
});

renderer.domElement.addEventListener(
  "wheel",
  (event) => {
    if (alpeccaViewMode === "orthographic") {
      alpeccaOrthographicZoom = THREE.MathUtils.clamp(alpeccaOrthographicZoom - event.deltaY * 0.001, 0.72, 1.55);
      updateOrthographicCamera();
      event.preventDefault();
      return;
    }
    const wheelSensitivity = event.shiftKey ? 0.0008 : 0.0012;
    if (event.shiftKey) {
      applyLook(event.deltaY, 0, wheelSensitivity);
    } else {
      applyLook(0, event.deltaY, wheelSensitivity);
    }
    renderer.domElement.focus();
    event.preventDefault();
  },
  { passive: false },
);

renderer.domElement.addEventListener("touchstart", (event) => {
  if (alpeccaViewMode === "orthographic") return;
  const touch = event.touches[0];
  if (!touch) return;
  lastTouch = { x: touch.clientX, y: touch.clientY };
  showMessage("Drag to look around", 2);
});

renderer.domElement.addEventListener(
  "touchmove",
  (event) => {
    if (alpeccaViewMode === "orthographic") return;
    const touch = event.touches[0];
    if (!touch || !lastTouch) return;
    applyLook(touch.clientX - lastTouch.x, touch.clientY - lastTouch.y, 0.004);
    lastTouch = { x: touch.clientX, y: touch.clientY };
    event.preventDefault();
  },
  { passive: false },
);

renderer.domElement.addEventListener("touchend", () => {
  lastTouch = null;
});

moveStick.addEventListener("pointerdown", (event) => {
  event.preventDefault();
  event.stopPropagation();
  movePointerId = event.pointerId;
  moveStick.setPointerCapture(event.pointerId);
  updateMoveStick(event.clientX, event.clientY);
  renderer.domElement.focus();
});

moveStick.addEventListener("pointermove", (event) => {
  if (event.pointerId !== movePointerId) return;
  event.preventDefault();
  updateMoveStick(event.clientX, event.clientY);
});

moveStick.addEventListener("pointerup", (event) => {
  if (event.pointerId !== movePointerId) return;
  event.preventDefault();
  resetMoveStick();
});

moveStick.addEventListener("pointercancel", (event) => {
  if (event.pointerId !== movePointerId) return;
  resetMoveStick();
});

touchInteract.addEventListener("pointerdown", (event) => {
  event.preventDefault();
  event.stopPropagation();
  renderer.domElement.focus();
  onInteract();
});

menuButton.addEventListener("click", (event) => {
  event.stopPropagation();
  setMenuOpen(menu.classList.contains("hidden"));
});

document.addEventListener("pointerlockchange", () => {
  if (document.pointerLockElement === renderer.domElement) {
    pointerLockBlocked = false;
    isDraggingLook = false;
    lastMouse = null;
    showMessage("Mouse locked. Press Esc to release.", 3);
  } else {
    showMessage("Mouse unlocked. Click the game to lock it again.", 3);
  }
});

document.addEventListener("pointerlockerror", () => {
  pointerLockBlocked = true;
  showMessage("Mouse lock was blocked by this browser. Click the game again, or use a desktop browser for full lock.", 4.5);
});

window.addEventListener("pagehide", persistAlpeccaPose);
