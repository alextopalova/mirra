import "./DirectionArrow.css";
import type { FitDirection } from "../lib/poseFit";

/**
 * Chevron paths for left/right, in a shared 0..100 viewBox.
 * A single chevron pointing the way to move — unambiguous for lateral
 * movement, so it's kept as-is (only forward/backward were replaced).
 */
const CHEVRON_PATHS: Record<"left" | "right", string[]> = {
  left: ["M 65,15 L 20,50 L 65,85"],
  right: ["M 35,15 L 80,50 L 35,85"],
};

/**
 * Solid 3D perspective block-arrow outlines for forward/backward, in the
 * same shared 0..100 viewBox.
 *
 * Geometry reads as an arrow lying flat on the floor in front of the
 * camera, seen in perspective — the near end (bottom of screen, closest to
 * the shopper standing at the mirror) is drawn large, the far end small,
 * exactly like a real object would foreshorten:
 *  - forward ("come closer"): the arrowHEAD is the near/large part, tip
 *    pointing down the screen at the viewer — like it's arriving at you.
 *    The tail (shaft) recedes upward, thin, into the distance.
 *  - backward ("step back"): the TAIL is the near/large part — a wide
 *    flat base at the bottom — receding and narrowing up the screen to a
 *    small arrowhead pointing away, like it's departing from you.
 * This near-big/far-small asymmetry (head-near for forward, tail-near for
 * backward) is what makes each shape unambiguously read as "toward" vs
 * "away" rather than just "up" vs "down".
 */
const ARROW_3D_POINTS: Record<"forward" | "backward", string> = {
  forward: "44,10 56,10 61,50 83,55 50,93 17,55 39,50",
  backward: "20,90 80,90 63,48 72,42 50,9 28,42 37,48",
};

/**
 * Large movement-direction arrow overlaid on the live camera stage —
 * "which way to move" for a shopper standing several metres back, who
 * can't read small text. Purely graphical (`aria-hidden`); the accessible/
 * short label is the existing hint paragraph below the stage.
 */
export function DirectionArrow({ direction }: { direction: FitDirection }) {
  if (!direction) return null;

  if (direction === "forward" || direction === "backward") {
    const points = ARROW_3D_POINTS[direction];
    return (
      <div className={`direction-arrow direction-arrow--${direction}`} aria-hidden="true">
        <svg className="direction-arrow-svg" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
          <g className="direction-arrow-3d">
            {/* Extruded side face: same outline, offset down-right, giving the
                solid shape physical depth (a consistent top-left "light
                source"). Plays the halo/shadow role the flat chevrons used
                a stroke for. */}
            <polygon className="direction-arrow-3d-side" points={points} transform="translate(6,6)" />
            {/* Lit top face, drawn on top unshifted — the "core" the shopper
                actually reads as the arrow. */}
            <polygon className="direction-arrow-3d-face" points={points} />
          </g>
        </svg>
      </div>
    );
  }

  const paths = CHEVRON_PATHS[direction];
  return (
    <div className={`direction-arrow direction-arrow--${direction}`} aria-hidden="true">
      <svg className="direction-arrow-svg" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
        {paths.map((d, i) => (
          <g className="direction-arrow-chevron" key={i}>
            <path className="direction-arrow-halo" d={d} />
            <path className="direction-arrow-core" d={d} />
          </g>
        ))}
      </svg>
    </div>
  );
}
