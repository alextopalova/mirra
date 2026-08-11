import type { Screen } from "../api/types";
import "./ProgressRail.css";

/**
 * The four things a shopper actually does, in order. Several screens map to
 * one step on purpose — "analyzing" is the tail of Details, not a stage the
 * shopper can act on, and showing it as its own checkpoint would advertise a
 * wait rather than hide it.
 */
const STEPS = [
  { key: "scan", label: "Scan", screens: ["capture"] },
  { key: "details", label: "Details", screens: ["measurements", "analyzing"] },
  { key: "profile", label: "Profile", screens: ["report"] },
  { key: "fitting", label: "Fitting room", screens: ["fitting", "getit"] },
] as const satisfies ReadonlyArray<{ key: string; label: string; screens: readonly Screen[] }>;

/** -1 before the flow begins ("start"), so no step reads as current there. */
function activeIndex(screen: Screen): number {
  return STEPS.findIndex((s) => (s.screens as readonly Screen[]).includes(screen));
}

/**
 * Where-you-are indicator across the top of every in-flow screen.
 *
 * Deliberately NOT navigable: each step depends on the output of the one
 * before it (there is no profile without a scan), so a tappable checkpoint
 * would offer a jump that can only dead-end. It's rendered as a <ol> of
 * plain elements with no button/link semantics — nothing to focus, nothing
 * to press — with `aria-current="step"` carrying the position for screen
 * readers instead.
 */
export function ProgressRail({ screen }: { screen: Screen }) {
  const active = activeIndex(screen);
  if (active < 0) return null;

  return (
    <nav className="rail" aria-label="Your progress">
      <ol className="rail-track">
        {STEPS.map((step, i) => {
          const state = i < active ? "done" : i === active ? "current" : "ahead";
          return (
            <li
              key={step.key}
              className={`rail-step rail-step--${state}`}
              aria-current={state === "current" ? "step" : undefined}
            >
              <span className="rail-dot" aria-hidden="true" />
              <span className="rail-label">{step.label}</span>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
