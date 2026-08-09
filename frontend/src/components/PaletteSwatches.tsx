import "./PaletteSwatches.css";

// Short, confident mood words per classic season family. Matched loosely
// (e.g. "Soft Autumn" still reads as autumn) so 12-season naming still
// gets a sensible read instead of falling through to the generic line.
const SEASON_MOOD: [string, string][] = [
  ["spring", "Warm · Clear · Bright"],
  ["summer", "Cool · Soft · Muted"],
  ["autumn", "Warm · Rich · Earthy"],
  ["winter", "Cool · Bold · Clear"],
];

function seasonMood(season: string): string {
  const s = season.toLowerCase();
  const match = SEASON_MOOD.find(([key]) => s.includes(key));
  return match ? match[1] : "Curated for your undertone";
}

export function PaletteSwatches({ season, colors }: { season: string; colors: string[] }) {
  const [hero, ...rest] = colors;

  return (
    <div className="palette-swatches">
      <div className="palette-header">
        <p className="palette-eyebrow">Your colours</p>
        <h3 className="palette-season">{season}</h3>
        <p className="palette-mood">{seasonMood(season)}</p>
      </div>

      <div className="palette-story">
        {hero && (
          // Swatch background is user data (a hex color from the analysis result), not styling —
          // it must stay a dynamic inline style.
          <div className="palette-hero" style={{ background: hero }} />
        )}
        {rest.length > 0 && (
          <div className="palette-support">
            {rest.map((c) => (
              <div key={c} className="palette-chip" style={{ background: c }} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
