import "./DirectionArrow.css";
import type { FitDirection } from "../lib/poseFit";

/**
 * Chevron paths per direction, in a shared 0..100 viewBox.
 *
 * forward/backward use a PAIR of chevrons that visually diverge (spread
 * apart, pointing away from each other) or converge (pull together,
 * pointing at each other) — the same "expand" / "collapse" chevron
 * language as a fullscreen toggle icon. That reads unambiguously as
 * "get bigger in frame" (come closer) vs "get smaller in frame" (step
 * back) without depending on any assumption about which screen edge is
 * "near" vs "far".
 * left/right use a single chevron pointing the way to move.
 */
const CHEVRON_PATHS: Record<Exclude<FitDirection, null>, string[]> = {
  // Gap between the pair is deliberately wide relative to the stroke width
  // (see DirectionArrow.css) — too tight and the halo strokes bridge the
  // gap, merging the pair into a solid "X" (reads as error/cancel — the
  // opposite of the intended meaning) instead of two distinct chevrons.
  forward: ["M 15,40 L 50,10 L 85,40", "M 15,60 L 50,90 L 85,60"],
  backward: ["M 15,10 L 50,40 L 85,10", "M 15,90 L 50,60 L 85,90"],
  left: ["M 65,15 L 20,50 L 65,85"],
  right: ["M 35,15 L 80,50 L 35,85"],
};

/**
 * Large movement-direction arrow overlaid on the live camera stage —
 * "which way to move" for a shopper standing several metres back, who
 * can't read small text. Purely graphical (`aria-hidden`); the accessible/
 * short label is the existing hint paragraph below the stage.
 */
export function DirectionArrow({ direction }: { direction: FitDirection }) {
  if (!direction) return null;
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
