import { useState } from "react";
import { useSession } from "../state/session";
import { GlassPanel } from "../components/GlassPanel";
import { PrimaryButton } from "../components/PrimaryButton";
import "./getit.css";
import "./screen.css";

export function GetItScreen() {
  const { data, reset } = useSession();
  const rec = data.recommendations?.find((r) => r.garment.id === data.selectedId);
  const g = rec?.garment;
  const [added, setAdded] = useState(false);

  return (
    <div className="screen">
      <h2>Find it in store</h2>
      <GlassPanel>
        <h1 className="getit-title">{g?.name ?? "Your pick"}</h1>
        <p className="getit-detail">Location: {g?.location ?? "Women's · Aisle 3"}</p>
        <p className="getit-detail">In stock: {(g?.sizes_in_stock ?? ["S", "M", "L"]).join(" · ")}</p>
        {added && <p className="getit-confirm">Added to bag — pick it up at checkout.</p>}
      </GlassPanel>
      <div className="actions">
        <PrimaryButton
          label={added ? "Added ✓" : "Add to bag"}
          onClick={() => setAdded(true)}
          disabled={added}
        />
        <PrimaryButton label="Next customer" variant="ghost" onClick={reset} />
      </div>
    </div>
  );
}
