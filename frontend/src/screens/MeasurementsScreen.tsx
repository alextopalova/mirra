import { useState } from "react";
import { useSession } from "../state/session";
import { PrimaryButton } from "../components/PrimaryButton";
import { NumericKeypad } from "../components/NumericKeypad";
import { GlassPanel } from "../components/GlassPanel";
import "./screen.css";
import "./measurements.css";

/**
 * Height and weight, which the body analysis needs for BMI.
 *
 * Both values are shown SMALL and deliberately so. This screen stands on a
 * shop floor: the rest of the kiosk is sized to be read from several metres
 * back, and rendering someone's weight at that size broadcasts it to the
 * queue behind them. The numbers still have to be checkable by the person
 * typing them — a typo here skews the scan — so they're legible at arm's
 * length and no further. The keypad keeps its full touch size; only the
 * readout shrank.
 */
export function MeasurementsScreen() {
  const { go, update } = useSession();
  const [field, setField] = useState<"height" | "weight">("height");
  const [height, setHeight] = useState("");
  const [weight, setWeight] = useState("");
  const ready = height !== "" && weight !== "";

  const fieldPanel = (
    key: "height" | "weight",
    label: string,
    value: string,
    unit: string,
  ) => (
    <GlassPanel className={`measurement-field ${field === key ? "sel" : ""}`}>
      <button
        className="field-btn"
        onClick={() => setField(key)}
        aria-pressed={field === key}
      >
        <span className="field-label">{label}</span>
        <span className={`field-value${value ? "" : " field-value-empty"}`}>
          {value ? `${value} ${unit}` : "Tap to enter"}
        </span>
      </button>
    </GlassPanel>
  );

  return (
    <div className="screen screen-measurements">
      <h2>A couple of numbers</h2>
      <p className="measurements-hint">
        Enter your height, then your weight — tap a field to switch.
      </p>
      <div className="measurements-fields">
        {fieldPanel("height", "Height", height, "cm")}
        {fieldPanel("weight", "Weight", weight, "kg")}
      </div>
      <NumericKeypad
        value={field === "height" ? height : weight}
        onChange={field === "height" ? setHeight : setWeight}
      />
      <PrimaryButton label="Analyze me" disabled={!ready}
        onClick={() => { update({ heightCm: +height, weightKg: +weight }); go("analyzing"); }} />
    </div>
  );
}
