import { createContext, useContext, useState } from "react";
import type { Screen, BodyProfile, Palette, Recommendation } from "../api/types";

interface SessionData {
  frontPhoto?: string;  // dataURL
  sidePhoto?: string;
  heightCm?: number;
  weightKg?: number;
  profile?: BodyProfile;
  palette?: Palette;
  category?: string;
  occasion?: string;
  recommendations?: Recommendation[];
  selectedId?: string;
  tryOnImage?: string;  // dataURL/URL from VTO
}

interface Ctx {
  screen: Screen;
  data: SessionData;
  go: (s: Screen) => void;
  update: (patch: Partial<SessionData>) => void;
  reset: () => void;
}

const SessionCtx = createContext<Ctx | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [screen, setScreen] = useState<Screen>("start");
  const [data, setData] = useState<SessionData>({});
  const go = (s: Screen) => setScreen(s);
  const update = (patch: Partial<SessionData>) => setData((d) => ({ ...d, ...patch }));
  const reset = () => { setData({}); setScreen("start"); };
  return <SessionCtx.Provider value={{ screen, data, go, update, reset }}>{children}</SessionCtx.Provider>;
}

export function useSession() {
  const c = useContext(SessionCtx);
  if (!c) throw new Error("useSession outside provider");
  return c;
}
