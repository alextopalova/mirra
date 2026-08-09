// Pure framing-guidance logic for the capture screen's auto-capture feature.
// This never leaves the browser and never talks to the backend — it only
// decides when the shopper is well-framed enough to fire the shutter.
// (The backend does the real body measurement from the captured photos.)

/**
 * The live camera preview is shown flipped horizontally (`transform:
 * scaleX(-1)`) so it behaves like a real mirror — intuitive for "turn to
 * your side". The captured photo and the on-screen fit/hint logic must
 * match that same flip. If a given kiosk's camera should NOT be mirrored,
 * flip this single constant.
 */
export const MIRROR_PREVIEW = true;

// BlazePose (mediapipe pose_landmarker) landmark indices we care about for
// framing — see https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker
const LM = {
  nose: 0,
  leftShoulder: 11,
  rightShoulder: 12,
  leftHip: 23,
  rightHip: 24,
  leftAnkle: 27,
  rightAnkle: 28,
} as const;

const REQUIRED_LANDMARKS = [
  LM.leftShoulder,
  LM.rightShoulder,
  LM.leftHip,
  LM.rightHip,
  LM.leftAnkle,
  LM.rightAnkle,
];

const VISIBILITY_MIN = 0.5;

/**
 * Target bounding box for the body (shoulders/hips/ankles), expressed as a
 * fraction of the video frame (0..1). Matches the fraction of the frame the
 * PoseGuide anatomical silhouette occupies, with margin for tolerance.
 */
export const GUIDE_BOX = { xMin: 0.30, xMax: 0.70, yMin: 0.22, yMax: 0.90 };

const SIZE_TOLERANCE = 0.20; // fraction of guide height allowed too small/large
const CENTER_TOLERANCE = 0.09; // fraction of frame width allowed off-center
const CROP_MARGIN = 0.02; // landmark this close to a raw frame edge = cropped

export type FitStatus = "searching" | "adjust" | "fit";

export interface FitResult {
  status: FitStatus;
  hint: string;
}

export interface Landmark {
  x: number;
  y: number;
  visibility?: number;
}

const SEARCHING: FitResult = { status: "searching", hint: "Step into frame so your whole body is visible" };

/** Decide whether the detected body fits the guide, and what to tell the shopper. */
export function evaluateFit(landmarks: Landmark[] | undefined, mirror: boolean = MIRROR_PREVIEW): FitResult {
  if (!landmarks || landmarks.length === 0) return SEARCHING;

  for (const i of REQUIRED_LANDMARKS) {
    const lm = landmarks[i];
    if (!lm || (lm.visibility ?? 1) < VISIBILITY_MIN) return SEARCHING;
  }

  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const i of REQUIRED_LANDMARKS) {
    const lm = landmarks[i];
    minX = Math.min(minX, lm.x); maxX = Math.max(maxX, lm.x);
    minY = Math.min(minY, lm.y); maxY = Math.max(maxY, lm.y);
  }

  if (minY <= CROP_MARGIN || maxY >= 1 - CROP_MARGIN || minX <= CROP_MARGIN || maxX >= 1 - CROP_MARGIN) {
    return { status: "adjust", hint: "Step back" };
  }

  const bodyHeight = maxY - minY;
  const guideHeight = GUIDE_BOX.yMax - GUIDE_BOX.yMin;

  if (bodyHeight < guideHeight * (1 - SIZE_TOLERANCE)) return { status: "adjust", hint: "Come closer" };
  if (bodyHeight > guideHeight * (1 + SIZE_TOLERANCE)) return { status: "adjust", hint: "Step back" };

  const rawCenterX = (minX + maxX) / 2;
  // Raw landmark coordinates come from the unflipped video frame; mirror them
  // to on-screen (preview) space before comparing, so hint direction matches
  // what the shopper actually sees in the mirrored preview.
  const displayedCenterX = mirror ? 1 - rawCenterX : rawCenterX;
  const guideCenterX = (GUIDE_BOX.xMin + GUIDE_BOX.xMax) / 2;
  if (displayedCenterX < guideCenterX - CENTER_TOLERANCE) return { status: "adjust", hint: "Move right" };
  if (displayedCenterX > guideCenterX + CENTER_TOLERANCE) return { status: "adjust", hint: "Move left" };

  return { status: "fit", hint: "Hold still" };
}
