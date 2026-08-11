import { useSession } from "../state/session";
import { PrimaryButton } from "../components/PrimaryButton";
import { ErrorState } from "../components/ErrorState";
import { PaletteSwatches } from "../components/PaletteSwatches";
import { BodyTypeDiagram } from "../components/BodyTypeDiagram";
import { SHAPE_RULES, isFruit, isJapanese, type Fruit, type Japanese } from "../lib/styleRules";
import "./report.css";
import "./screen.css";

/** "a" or "an" for a word we don't control the spelling of — the shape and
 *  season names come from the analysis. Vowel letters cover every season and
 *  most shapes; "hourglass" is the one that needs the silent-h exception. */
function article(word: string): string {
  const w = word.trim().toLowerCase();
  if (w.startsWith("hour")) return "an";
  return /^[aeiou]/.test(w) ? "an" : "a";
}

export function ReportScreen() {
  const { data, go, reset } = useSession();
  const { profile, palette } = data;

  if (!profile || !palette) {
    return (
      <ErrorState
        message="We couldn't find your scan results."
        onRetry={() => go("capture")}
        onStartOver={reset}
      />
    );
  }

  // The API is free-form here, so both keys fall back to a known value
  // rather than letting an unrecognised one blank out half the screen.
  const shapeKey: Fruit = isFruit(profile.fruit) ? profile.fruit : "rectangle";
  const boneKey: Japanese = isJapanese(profile.japanese) ? profile.japanese : "natural";
  const shapeLabel = SHAPE_RULES[shapeKey].label;

  return (
    <div className="screen screen-wide report">
      <h1 className="report-headline">
        You're {article(shapeLabel)} {shapeLabel}, and {article(palette.season)}{" "}
        <span className="report-headline-season">{palette.season}</span>
      </h1>

      {/* Two self-contained cards: everything about your shape lives inside
          the first, everything about your colours inside the second. The
          earlier version ran the wear/skip advice as a band under both,
          which made shape guidance look like it belonged to the palette. */}
      <div className="report-cards">
        <BodyTypeDiagram
          fruit={shapeKey}
          bone={boneKey}
          weights={profile.japanese_weights}
        />
        <PaletteSwatches season={palette.season} colors={palette.colors} />
      </div>

      <footer className="report-footer">
        <PrimaryButton label="See what fits" onClick={() => go("fitting")} />
      </footer>
    </div>
  );
}
