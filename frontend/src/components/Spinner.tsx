import "./Spinner.css";

export function Spinner({ label }: { label: string }) {
  return (
    <div className="spinner">
      <div className="spinner-ring" />
      <h2>{label}</h2>
    </div>
  );
}
