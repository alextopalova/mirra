import "./PaletteSwatches.css";

export function PaletteSwatches({ colors }: { colors: string[] }) {
  return (
    <div className="palette-swatches">
      {colors.map((c) => (
        // Swatch background is user data (a hex color from the analysis result), not styling —
        // it must stay a dynamic inline style.
        <div key={c} className="palette-swatch" style={{ background: c }} />
      ))}
    </div>
  );
}
