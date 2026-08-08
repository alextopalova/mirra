import { useSession } from "./state/session";
// Screen imports are added here as each screen is built (see Task 1.4+).
// Until then, every screen falls through to the placeholder below.

export default function App() {
  const { screen } = useSession();
  switch (screen) {
    default: return <div style={{ padding: 40 }}>TODO: {screen}</div>;
  }
}
