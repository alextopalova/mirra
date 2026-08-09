import "./PoseGuide.css";
import {
  GUIDE_VIEWBOX,
  FRONT_OUTLINE_PATHS,
  SIDE_OUTLINE_PATHS,
} from "./poseGuidePaths";

export type GuideState = "idle" | "searching" | "adjust" | "fit";

/**
 * The "stand here" body outline overlaid on the camera preview.
 *
 * Artwork comes from the designer-supplied silhouettes (see poseGuidePaths.ts).
 * Those are filled contour shapes rather than stroked outlines, so the colour is
 * driven by `fill` in PoseGuide.css — which also handles the per-state treatment
 * (dim while searching, brighter while adjusting, accent + glow once the shopper
 * fits the guide).
 */
export function PoseGuide({
  variant,
  state = "idle",
}: {
  variant: "front" | "side";
  state?: GuideState;
}) {
  const paths = variant === "front" ? FRONT_OUTLINE_PATHS : SIDE_OUTLINE_PATHS;

  return (
    <svg
      className={`pose-guide pose-guide--${state}`}
      viewBox={GUIDE_VIEWBOX}
      preserveAspectRatio="xMidYMid meet"
      aria-hidden="true"
    >
      {paths.map((d, i) => (
        <path key={i} className="pose-guide-path" d={d} />
      ))}
    </svg>
  );
}
