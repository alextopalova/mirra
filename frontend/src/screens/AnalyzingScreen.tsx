import { useEffect } from "react";
import { useSession } from "../state/session";
import { analyzeBody } from "../api/client";
import { Spinner } from "../components/Spinner";

export function AnalyzingScreen() {
  const { data, update, go } = useSession();
  useEffect(() => {
    analyzeBody({
      frontPhoto: data.frontPhoto!, sidePhoto: data.sidePhoto,
      heightCm: data.heightCm!, weightKg: data.weightKg!,
    }).then(({ profile, palette }) => { update({ profile, palette }); go("report"); });
  }, []);
  return <Spinner label="Reading your colors and frame…" />;
}
