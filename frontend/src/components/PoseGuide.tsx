export function PoseGuide({ variant }: { variant: "front" | "side" }) {
  return (
    <svg className="pose-guide" viewBox="0 0 200 400" preserveAspectRatio="xMidYMid meet"
         aria-hidden style={{ opacity: 0.5 }}>
      {variant === "front" ? (
        <path d="M100 30 a20 20 0 1 0 0.1 0 M100 70 v70 M60 90 h80 M100 140 l-25 120 M100 140 l25 120"
              stroke="white" strokeWidth="3" fill="none" strokeLinecap="round" />
      ) : (
        <path d="M100 30 a20 20 0 1 0 0.1 0 M100 70 q20 40 0 90 q-15 60 0 100"
              stroke="white" strokeWidth="3" fill="none" strokeLinecap="round" />
      )}
    </svg>
  );
}
