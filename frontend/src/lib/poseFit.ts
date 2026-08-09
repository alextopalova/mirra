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
 *
 * Derived from PoseGuide's rendering geometry (see PoseGuide.css), which
 * locks the guide's height to 96% of the frame — a 2% inset top and
 * bottom — with its width centred and derived from GUIDE_VIEWBOX's
 * (771 x 1060) aspect ratio:
 *
 *   frameFraction(viewBoxYFraction) = 0.02 + viewBoxYFraction * 0.96
 *
 * The previous box's numbers (yMin 0.22 / yMax 0.90) were themselves
 * already a fraction-of-viewBox estimate of where the shoulders and ankles
 * fall on the silhouette (roughly 22% and 90% of the way down the artwork).
 * Running those same fractions through the transform above keeps the
 * *anatomical* target unchanged while re-expressing it in the new,
 * height-locked frame coordinates:
 *
 *   yMin = 0.02 + 0.22 * 0.96 = 0.231  ->  0.23
 *   yMax = 0.02 + 0.90 * 0.96 = 0.884  ->  0.88
 *
 * That vertical mapping — and therefore yMin/yMax below — holds across
 * every container aspect ratio: the guide's height is always exactly 96%
 * of the frame, regardless of width (only its *width*, and therefore how
 * much of it may be clipped at the sides, varies with aspect — see
 * PoseGuide.css). xMin/xMax are only used via their midpoint (0.5) in
 * evaluateFit below, which is also aspect-invariant by construction (the
 * guide is always horizontally centred); the concrete 0.28/0.72 values are
 * a same-derivation estimate of the shoulder span at a representative
 * (non-clipped) aspect ratio, kept only for documentation/margin purposes.
 */
export const GUIDE_BOX = { xMin: 0.28, xMax: 0.72, yMin: 0.23, yMax: 0.88 };

const SIZE_TOLERANCE = 0.20; // fraction of guide height allowed too small/large
const CENTER_TOLERANCE = 0.09; // fraction of frame width allowed off-center
const CROP_MARGIN = 0.02; // landmark this close to a raw frame edge = cropped

export type FitStatus = "searching" | "adjust" | "fit";

/**
 * Machine-readable movement direction, kept separate from `hint` so the UI
 * can drive a large arrow overlay without parsing English text.
 * `forward` = too far away (needs to come closer / appear bigger in frame).
 * `backward` = too close / cropped (needs to step back / appear smaller).
 * `null` when the shopper is fit, or not yet detected (searching).
 */
export type FitDirection = "forward" | "backward" | "left" | "right" | null;

export interface FitResult {
  status: FitStatus;
  hint: string;
  direction: FitDirection;
}

export interface Landmark {
  x: number;
  y: number;
  visibility?: number;
}

const SEARCHING: FitResult = {
  status: "searching",
  hint: "Step into frame so your whole body is visible",
  direction: null,
};

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
    return { status: "adjust", hint: "Step back", direction: "backward" };
  }

  const bodyHeight = maxY - minY;
  const guideHeight = GUIDE_BOX.yMax - GUIDE_BOX.yMin;

  if (bodyHeight < guideHeight * (1 - SIZE_TOLERANCE)) return { status: "adjust", hint: "Come closer", direction: "forward" };
  if (bodyHeight > guideHeight * (1 + SIZE_TOLERANCE)) return { status: "adjust", hint: "Step back", direction: "backward" };

  const rawCenterX = (minX + maxX) / 2;
  // Raw landmark coordinates come from the unflipped video frame; mirror them
  // to on-screen (preview) space before comparing, so hint direction matches
  // what the shopper actually sees in the mirrored preview.
  const displayedCenterX = mirror ? 1 - rawCenterX : rawCenterX;
  const guideCenterX = (GUIDE_BOX.xMin + GUIDE_BOX.xMax) / 2;
  if (displayedCenterX < guideCenterX - CENTER_TOLERANCE) return { status: "adjust", hint: "Move right", direction: "right" };
  if (displayedCenterX > guideCenterX + CENTER_TOLERANCE) return { status: "adjust", hint: "Move left", direction: "left" };

  return { status: "fit", hint: "Hold still", direction: null };
}
