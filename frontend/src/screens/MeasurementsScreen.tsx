import { useState } from "react";
import { useSession } from "../state/session";
import { PrimaryButton } from "../components/PrimaryButton";
import { NumericKeypad } from "../components/NumericKeypad";
import { GlassPanel } from "../components/GlassPanel";
import "./screen.css";
import "./measurements.css";

export function MeasurementsScreen() {
  const { go, update } = useSession();
  const [field, setField] = useState<"height" | "weight">("height");
  const [height, setHeight] = useState("");
  const [weight, setWeight] = useState("");
  const ready = height !== "" && weight !== "";

  return (
    <div className="screen screen-measurements">
      <h2>A couple of numbers</h2>
      <p className="measurements-hint">
        Enter your height, then your weight — tap a field to switch.
      </p>
      <div className="measurements-fields">
        <GlassPanel className={`measurement-field ${field === "height" ? "sel" : ""}`}>
          <button
            className="field-btn"
            onClick={() => setField("height")}
            aria-pressed={field === "height"}
          >
            <p className="field-label">Height</p>
            <h1 className={height ? "" : "field-value-empty"}>
              {height ? (<>{height}<span style={{ fontSize: 24 }}> cm</span></>) : "Tap to enter"}
            </h1>
          </button>
        </GlassPanel>
        <GlassPanel className={`measurement-field ${field === "weight" ? "sel" : ""}`}>
          <button
            className="field-btn"
            onClick={() => setField("weight")}
            aria-pressed={field === "weight"}
          >
            <p className="field-label">Weight</p>
            <h1 className={weight ? "" : "field-value-empty"}>
              {weight ? (<>{weight}<span style={{ fontSize: 24 }}> kg</span></>) : "Tap to enter"}
            </h1>
          </button>
        </GlassPanel>
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
