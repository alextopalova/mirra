import type { Recommendation } from "../api/types";
import { resolveImageUrl } from "../api/client";

export function GarmentCard({ rec, onClick }: { rec: Recommendation; onClick: () => void }) {
  return (
    <div className="card" onClick={onClick}>
      <img src={resolveImageUrl(rec.garment.image_url)} alt={rec.garment.name} />
      <div className="card-body">
        <div style={{ fontSize: 19, fontWeight: 600 }}>{rec.garment.name}</div>
        <div className="reason">{rec.reasons[0]}</div>
      </div>
    </div>
  );
}
