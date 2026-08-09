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
 * fraction of the VISIBLE on-screen preview — i.e. of `.capture-video-area`
 * (0..1) — NOT of the raw camera frame. Matches the fraction of that visible
 * box the PoseGuide anatomical silhouette occupies, with margin for
 * tolerance.
 *
 * `.capture-video-area` now cover-fills `.capture-stage` (see capture.css):
 * the video is cropped, not letterboxed, so the visible preview is always
 * exactly the fixed, viewport-derived stage box — it never depends on the
 * camera's own aspect ratio at all any more. Because MediaPipe landmark
 * coordinates are normalised to the RAW (uncropped) camera frame, they must
 * be re-expressed in this same visible-fraction space — via
 * `computeCoverCrop` + the `crop` parameter of `evaluateFit` below — before
 * they can be compared to GUIDE_BOX.
 *
 * Derived from PoseGuide's rendering geometry (see PoseGuide.css), which
 * locks the guide's height to 96% of the visible box — a 2% inset top and
 * bottom — with its width centred and derived from GUIDE_VIEWBOX's
 * (771 x 1060) aspect ratio:
 *
 *   visibleFraction(viewBoxYFraction) = 0.02 + viewBoxYFraction * 0.96
 *
 * The previous box's numbers (yMin 0.22 / yMax 0.90) were themselves
 * already a fraction-of-viewBox estimate of where the shoulders and ankles
 * fall on the silhouette (roughly 22% and 90% of the way down the artwork).
 * Running those same fractions through the transform above keeps the
 * *anatomical* target unchanged while re-expressing it in the height-locked
 * coordinates:
 *
 *   yMin = 0.02 + 0.22 * 0.96 = 0.231  ->  0.23
 *   yMax = 0.02 + 0.90 * 0.96 = 0.884  ->  0.88
 *
 * That vertical mapping — and therefore yMin/yMax below — holds across
 * every container aspect ratio: the guide's height is always exactly 96%
 * of the visible box, regardless of width (only its *width*, and therefore
 * how much of it may be clipped at the sides, varies with aspect — see
 * PoseGuide.css). xMin/xMax are only used via their midpoint (0.5) in
 * evaluateFit below, which is also aspect-invariant by construction (the
 * guide is always horizontally centred); the concrete 0.28/0.72 values are
 * a same-derivation estimate of the shoulder span at a representative
 * (non-clipped) aspect ratio, kept only for documentation/margin purposes.
 */
export const GUIDE_BOX = { xMin: 0.28, xMax: 0.72, yMin: 0.23, yMax: 0.88 };

/**
 * A sub-rectangle of the RAW camera frame, expressed as fractions (0..1) of
 * that frame's own width/height: `[x0, x1] x [y0, y1]` is the region that
 * remains visible on screen once `object-fit: cover` has cropped the frame
 * to fill a differently-shaped container.
 */
export interface CropRect {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

/** No cropping at all — the whole raw frame is visible. Used as the default
 * for callers that haven't computed a real crop (e.g. before the video's
 * intrinsic size is known), matching the pre-`cover` behaviour. */
const FULL_FRAME_CROP: CropRect = { x0: 0, y0: 0, x1: 1, y1: 1 };

/**
 * Computes the same crop `object-fit: cover` performs, so landmark
 * coordinates (normalised to the raw camera frame) can be re-expressed as
 * fractions of the visible, on-screen crop — see `evaluateFit`'s `crop`
 * parameter and GUIDE_BOX's docs above.
 *
 * `cover` scales the video by `max(containerW/videoW, containerH/videoH)` —
 * i.e. by whichever axis needs to grow *more* to fully cover the container —
 * so the OTHER axis ends up larger than the container and gets cropped,
 * symmetrically, on both edges. Working directly in aspect-ratio terms
 * (rather than through intermediate pixel sizes) avoids that intermediate
 * scale factor entirely:
 *
 *   videoAspect > containerAspect  → video is relatively wider → cover
 *     matches heights, so the excess WIDTH is cropped off the left/right;
 *     the visible width fraction of the raw frame is containerAspect/videoAspect.
 *   videoAspect < containerAspect  → video is relatively taller (narrower)
 *     → cover matches widths, so the excess HEIGHT is cropped off the
 *     top/bottom; the visible height fraction is videoAspect/containerAspect.
 *   videoAspect === containerAspect → no crop at all.
 *
 * Returns `FULL_FRAME_CROP` (no-op) if any dimension is unknown/zero (e.g.
 * camera metadata hasn't loaded yet), which is the safe default.
 */
export function computeCoverCrop(
  videoWidth: number,
  videoHeight: number,
  containerWidth: number,
  containerHeight: number
): CropRect {
  if (!videoWidth || !videoHeight || !containerWidth || !containerHeight) {
    return FULL_FRAME_CROP;
  }

  const videoAspect = videoWidth / videoHeight;
  const containerAspect = containerWidth / containerHeight;

  let visibleFracX = 1;
  let visibleFracY = 1;
  if (videoAspect > containerAspect) {
    visibleFracX = containerAspect / videoAspect;
  } else if (videoAspect < containerAspect) {
    visibleFracY = videoAspect / containerAspect;
  }

  const x0 = (1 - visibleFracX) / 2;
  const y0 = (1 - visibleFracY) / 2;
  return { x0, y0, x1: 1 - x0, y1: 1 - y0 };
}

/** Maps a raw-frame fraction into visible-crop-fraction space, given the
 * crop's extent along that axis (`lo`..`hi`, both in raw-frame fractions).
 * Values outside the crop map outside `0..1`, which is intentional: the
 * CROP_MARGIN edge check in `evaluateFit` below relies on it to detect a
 * body that's fully outside the visible rect, not just near its edge. */
function toVisibleFraction(value: number, lo: number, hi: number): number {
  const span = hi - lo;
  if (span <= 0) return value;
  return (value - lo) / span;
}

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

/**
 * Decide whether the detected body fits the guide, and what to tell the
 * shopper.
 *
 * `crop` is the raw-frame sub-rectangle that's actually visible on screen
 * (see `computeCoverCrop`) — landmarks are mapped into that same
 * visible-fraction space (composing FIRST, before the mirror flip below)
 * so they land in the same coordinate space as GUIDE_BOX, which describes
 * the on-screen guide. Defaults to "no crop" (the whole raw frame is
 * visible), matching the pre-`cover` behaviour, for any caller that hasn't
 * computed a real crop yet.
 */
export function evaluateFit(
  landmarks: Landmark[] | undefined,
  crop: CropRect = FULL_FRAME_CROP,
  mirror: boolean = MIRROR_PREVIEW
): FitResult {
  if (!landmarks || landmarks.length === 0) return SEARCHING;

  for (const i of REQUIRED_LANDMARKS) {
    const lm = landmarks[i];
    if (!lm || (lm.visibility ?? 1) < VISIBILITY_MIN) return SEARCHING;
  }

  // Bounding box in VISIBLE-CROP fraction space (0..1 = the on-screen
  // preview, same space GUIDE_BOX is defined in) — not raw-frame space.
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const i of REQUIRED_LANDMARKS) {
    const lm = landmarks[i];
    const x = toVisibleFraction(lm.x, crop.x0, crop.x1);
    const y = toVisibleFraction(lm.y, crop.y0, crop.y1);
    minX = Math.min(minX, x); maxX = Math.max(maxX, x);
    minY = Math.min(minY, y); maxY = Math.max(maxY, y);
  }

  // "Near/past the edge" now means near/past the VISIBLE crop's edge, not
  // the raw sensor's edge — a landmark can be well inside the raw frame yet
  // already cropped out of what the shopper can see, and that must count as
  // "step back" too (values map outside 0..1 in that case).
  if (minY <= CROP_MARGIN || maxY >= 1 - CROP_MARGIN || minX <= CROP_MARGIN || maxX >= 1 - CROP_MARGIN) {
    return { status: "adjust", hint: "Step back", direction: "backward" };
  }

  const bodyHeight = maxY - minY;
  const guideHeight = GUIDE_BOX.yMax - GUIDE_BOX.yMin;

  if (bodyHeight < guideHeight * (1 - SIZE_TOLERANCE)) return { status: "adjust", hint: "Come closer", direction: "forward" };
  if (bodyHeight > guideHeight * (1 + SIZE_TOLERANCE)) return { status: "adjust", hint: "Step back", direction: "backward" };

  const visibleCenterX = (minX + maxX) / 2;
  // Cropping (above) is a symmetric centre-crop of the raw frame, so it's
  // unaffected by mirroring either way; the mirror flip is a presentational
  // step applied on TOP of the already-cropped visible image (CSS
  // `transform: scaleX(-1)` on the video element, after `object-fit` has
  // done its cropping) — so it must compose AFTER the crop mapping above,
  // exactly as the preview itself renders: crop, then flip.
  const displayedCenterX = mirror ? 1 - visibleCenterX : visibleCenterX;
  const guideCenterX = (GUIDE_BOX.xMin + GUIDE_BOX.xMax) / 2;
  if (displayedCenterX < guideCenterX - CENTER_TOLERANCE) return { status: "adjust", hint: "Move right", direction: "right" };
  if (displayedCenterX > guideCenterX + CENTER_TOLERANCE) return { status: "adjust", hint: "Move left", direction: "left" };

  return { status: "fit", hint: "Hold still", direction: null };
}
