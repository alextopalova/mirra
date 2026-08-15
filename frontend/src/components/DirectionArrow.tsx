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
 * Supplied floor-arrow artwork for forward/backward (move_closer.svg and
 * move_back.svg), inlined rather than referenced as <img>.
 *
 * Inlined because the arrows have to be blue: an <img> is an opaque box the
 * page can't recolour, so the fill would be stuck at the artwork's black.
 * As inline SVG the shapes inherit `fill`/`stroke` from CSS, which also
 * lets them keep the white outline + dark shadow the older arrows used to
 * stay legible against arbitrary camera video.
 *
 * Each keeps its own source viewBox — they are different proportions
 * (384x497 vs 429x416) and normalising them to a shared square would
 * distort one of the two.
 *
 * Direction convention comes from the artwork: `forward` points UP, into
 * the scene ("walk toward the mirror"), and `backward` points DOWN, out at
 * the viewer ("step away from it").
 */
const FLOOR_ARROWS: Record<"forward" | "backward", { viewBox: string; paths: string[] }> = {
  forward: {
    viewBox: "0 0 384 497",
    paths: [
      "M253.504 160.07L276.5 441.517V465.334L247.405 126.529L253.504 160.07Z",
      "M1 116H383V161H1V116Z",
      "M104.927 443L105.003 441.929L128.876 105.929L128.942 105H252.388L252.458 105.924L277.997 441.924L278.079 443H104.927Z",
      "M2.00003 115H382L190.462 0L2.00003 115Z",
      "M105 441H278V496H105V441Z",
    ],
  },
  backward: {
    viewBox: "0 0 429 416",
    paths: [
      "M295 0.213135V35.9954L294.995 36.0442L279.245 196.311L279.156 197.213H271.887L272.006 196.107L293.006 0.106689L295 0.213135Z",
      "M132 0.213135V35.9954L132.005 36.0442L147.755 196.311L147.844 197.213H155.113L154.994 196.107L133.994 0.106689L132 0.213135Z",
      "M134 0.213135H293L270.802 212.213H156.568L134 0.213135Z",
      "M424 197.213H4L215.7 357.213L424 197.213Z",
      "M218 413.296L216.375 411.993L1.375 239.667L1 239.366V195.227L2.5957 196.409L217.596 355.783L218 356.083V413.296Z",
      "M213 413.3L214.627 411.992L427.627 240.792L428 240.492V195.22L426.402 196.411L213.402 355.222L213 355.522V413.3Z",
    ],
  },
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
    const art = FLOOR_ARROWS[direction];
    return (
      <div className={`direction-arrow direction-arrow--${direction}`} aria-hidden="true">
        <svg
          className="direction-arrow-art-svg"
          viewBox={art.viewBox}
          preserveAspectRatio="xMidYMid meet"
        >
          <g className="direction-arrow-art">
            {art.paths.map((d) => (
              <path key={d} d={d} />
            ))}
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
