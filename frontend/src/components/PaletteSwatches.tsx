import { colorName } from "../lib/colorNames";
import { seasonRule } from "../lib/styleRules";
import "./PaletteSwatches.css";

/**
 * The colour card: your season, the shades that belong to it, and the ones
 * to leave on the rail.
 *
 * Every swatch is named, because a named colour is a shopping list and an
 * unnamed grid of colour is decoration.
 */
export function PaletteSwatches({ season, colors }: { season: string; colors: string[] }) {
  const rule = seasonRule(season);

  return (
    <section className="card palette">
      <p className="eyebrow">Your colours</p>

      <div className="palette-head">
        <h2 className="palette-season">{season}</h2>
        <p className="palette-mood">{rule.mood}</p>
      </div>

      <ul className="palette-grid">
        {colors.map((c) => {
          const name = colorName(c);
          return (
            <li key={c} className="palette-swatch">
              {/* Swatch fill is user data (a hex from the analysis), not
                  styling — it has to stay a dynamic inline style. */}
              <span className="palette-chip" style={{ background: c }} />
              <span className="palette-chip-name">{name ?? c}</span>
            </li>
          );
        })}
      </ul>

      {rule.skip.length > 0 && (
        <div>
          <p className="eyebrow">Skip</p>
          <ul className="palette-skip-list">
            {rule.skip.map((c) => (
              <li key={c.name}>
                <span className="palette-skip-dot" style={{ background: c.hex }} />
                {c.name}
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="palette-metals">
        <span className="palette-metals-label">Jewellery</span>
        {rule.metals}
      </p>
    </section>
  );
}
