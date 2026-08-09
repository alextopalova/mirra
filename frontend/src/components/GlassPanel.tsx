import "./GlassPanel.css";

export function GlassPanel({ children, className = "" }: {
  children: React.ReactNode; className?: string;
}) {
  return <div className={`glass-panel ${className}`}>{children}</div>;
}
