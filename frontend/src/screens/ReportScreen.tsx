import { useSession } from "../state/session";
import { GlassPanel } from "../components/GlassPanel";
import { PrimaryButton } from "../components/PrimaryButton";
import { ErrorState } from "../components/ErrorState";
import { PaletteSwatches } from "../components/PaletteSwatches";
import { BodyTypeDiagram } from "../components/BodyTypeDiagram";
import "./report.css";
import "./screen.css";

const FRUIT_LABELS: Record<string, string> = {
  pear: "Pear",
  apple: "Apple",
  hourglass: "Hourglass",
  rectangle: "Rectangle",
  "inverted-triangle": "Inverted Triangle",
};

function fruitLabel(fruit: string): string {
  return FRUIT_LABELS[fruit] ?? fruit.charAt(0).toUpperCase() + fruit.slice(1);
}

function cap(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
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

  // The headline is the single "who you are" statement: season + body
  // shape together. Composed from the raw fields (not profile.summary)
  // so season can lead and the two halves can wrap independently on a
  // narrow portrait viewport instead of breaking mid-word.
  const identityLine = `${fruitLabel(profile.fruit)}, ${cap(profile.japanese)}-leaning`;

  return (
    <div className="screen">
      <div className="report-header">
        <span className="report-eyebrow">Your style profile</span>
        <h1 className="report-headline">
          <span className="report-headline-part">{palette.season}</span>
          <span className="report-headline-sep" aria-hidden="true">·</span>
          <span className="report-headline-part">{identityLine}</span>
        </h1>
      </div>

      <p className="report-section-label">What this means for you</p>

      <div className="report-body">
        <div className="report-shape">
          <BodyTypeDiagram
            fruit={profile.fruit}
            japanese={profile.japanese}
            japaneseWeights={profile.japanese_weights}
          />
        </div>
        <GlassPanel className="report-colors">
          <PaletteSwatches season={palette.season} colors={palette.colors} />
        </GlassPanel>
      </div>

      <div className="report-cta">
        <p className="report-cta-label">Next step</p>
        <PrimaryButton label="Try on your matches →" onClick={() => go("shop")} />
      </div>
    </div>
  );
}
