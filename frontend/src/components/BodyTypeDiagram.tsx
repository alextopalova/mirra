import "./BodyTypeDiagram.css";

export function BodyTypeDiagram({ fruit, japanese }: { fruit: string; japanese: string }) {
  return (
    <div className="body-type-diagram">
      <svg viewBox="0 0 120 200" width="120" height="200" aria-hidden>
        <path d="M60 20 a14 14 0 1 0 0.1 0 M40 60 h40 l-8 50 h-24 z M52 110 l-10 70 M68 110 l10 70"
              stroke="var(--accent)" strokeWidth="4" fill="none" strokeLinecap="round" />
      </svg>
      <div className="body-type-diagram-fruit">{fruit}</div>
      <div className="body-type-diagram-japanese">{japanese} bone type</div>
    </div>
  );
}
