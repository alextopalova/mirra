import "./NumericKeypad.css";

export function NumericKeypad({ value, onChange, max = 3 }: {
  value: string; onChange: (next: string) => void; max?: number;
}) {
  const press = (d: string) => { if (value.length < max) onChange(value + d); };
  const back = () => onChange(value.slice(0, -1));
  return (
    <div className="keypad">
      {["1","2","3","4","5","6","7","8","9"].map((d) => (
        <button key={d} onClick={() => press(d)}>{d}</button>
      ))}
      <button onClick={back}>⌫</button>
      <button onClick={() => press("0")}>0</button>
      <button onClick={() => onChange("")}>C</button>
    </div>
  );
}
