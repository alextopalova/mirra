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
    <div className="screen">
      <h2>A couple of numbers</h2>
      <div style={{ display: "flex", gap: 24 }}>
        <GlassPanel className={field === "height" ? "sel" : ""}>
          <button className="field-btn" onClick={() => setField("height")}>
            <p>Height</p>
            <h1>{height || "—"}<span style={{ fontSize: 24 }}> cm</span></h1>
          </button>
        </GlassPanel>
        <GlassPanel className={field === "weight" ? "sel" : ""}>
          <button className="field-btn" onClick={() => setField("weight")}>
            <p>Weight</p>
            <h1>{weight || "—"}<span style={{ fontSize: 24 }}> kg</span></h1>
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
