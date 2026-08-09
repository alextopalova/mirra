import { useSession } from "../state/session";
import { GlassPanel } from "../components/GlassPanel";
import { PrimaryButton } from "../components/PrimaryButton";
import { ErrorState } from "../components/ErrorState";
import { PaletteSwatches } from "../components/PaletteSwatches";
import { BodyTypeDiagram } from "../components/BodyTypeDiagram";
import "./report.css";
import "./screen.css";

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

  return (
    <div className="screen">
      <h2>{profile.summary}</h2>
      <div className="report-grid">
        <GlassPanel>
          <p>Your body type</p>
          <BodyTypeDiagram fruit={profile.fruit} japanese={profile.japanese} />
        </GlassPanel>
        <GlassPanel>
          <p>Your colors — {palette.season}</p>
          <div className="report-swatches"><PaletteSwatches colors={palette.colors} /></div>
        </GlassPanel>
      </div>
      <div className="report-cta">
        <PrimaryButton label="Try on your matches →" onClick={() => go("shop")} />
      </div>
    </div>
  );
}
