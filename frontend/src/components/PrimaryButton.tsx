import "./PrimaryButton.css";

export function PrimaryButton({ label, onClick, disabled = false, variant = "solid" }: {
  label: string; onClick: () => void; disabled?: boolean; variant?: "solid" | "ghost";
}) {
  return (
    <button className={`btn btn-${variant}`} onClick={onClick} disabled={disabled}>
      {label}
    </button>
  );
}
