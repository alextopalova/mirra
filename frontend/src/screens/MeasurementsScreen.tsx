import { useState } from "react";
import { useSession } from "../state/session";
import { PrimaryButton } from "../components/PrimaryButton";
import { NumericKeypad } from "../components/NumericKeypad";
import "./screen.css";
import "./measurements.css";

/**
 * Height and weight, which the body analysis needs for BMI.
 *
 * Each field is shaped like a text input — a label above a recessed box —
 * because that is the one shape every shopper already reads as "you type
 * here", and this screen has no real input to borrow the affordance from.
 * The unit rides inside the box as a chip, so "cm" and "kg" are legible
 * before anything has been typed and the number never has to carry them.
 *
 * The values are still shown SMALL and deliberately so. This screen stands
 * on a shop floor: the rest of the kiosk is sized to be read from several
 * metres back, and rendering someone's weight at that size broadcasts it to
 * the queue behind them. The number is sized to be proof-read at arm's
 * length and no further — a typo here skews the scan.
 *
 * Fields, keypad and confirm button share one column (see
 * `.measurements-col`) so the screen reads as a single stack of controls.
 */
export function MeasurementsScreen() {
  const { go, update } = useSession();
  const [field, setField] = useState<"height" | "weight">("height");
  const [height, setHeight] = useState("");
  const [weight, setWeight] = useState("");
  const ready = height !== "" && weight !== "";

  const numberField = (
    key: "height" | "weight",
    label: string,
    value: string,
    unit: string,
  ) => {
    const selected = field === key;
    return (
      <button
        className={`measurement-field${selected ? " is-selected" : ""}`}
        onClick={() => setField(key)}
        aria-pressed={selected}
      >
        <span className="field-label">{label}</span>
        <span className="field-box">
          <span className={`field-value${value ? "" : " field-value-empty"}`}>
            {value || "Tap to enter"}
            {/* Only on the field being edited, and only once there is
                something to sit after: a caret in an empty box would read
                as a stray mark next to the placeholder. */}
            {value && selected && <span className="field-caret" aria-hidden="true" />}
          </span>
          <span className="field-unit">{unit}</span>
        </span>
      </button>
    );
  };

  return (
    <div className="screen screen-measurements">
      <h2>A couple of numbers</h2>
      <p className="measurements-hint">
        Enter your height, then your weight — tap a field to switch.
      </p>
      <div className="measurements-col">
        <div className="measurements-fields">
          {numberField("height", "Height", height, "cm")}
          {numberField("weight", "Weight", weight, "kg")}
        </div>
        <NumericKeypad
          value={field === "height" ? height : weight}
          onChange={field === "height" ? setHeight : setWeight}
        />
        <PrimaryButton label="Analyze me" disabled={!ready}
          onClick={() => { update({ heightCm: +height, weightKg: +weight }); go("analyzing"); }} />
      </div>
    </div>
  );
}
