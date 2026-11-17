import { Component, lazy, Suspense, useState, type ReactNode } from "react";

import { isUsageAdmin } from "../data/usageAdminFlag";

const HeatmapMode = lazy(() =>
  import("../features/usageAdmin/HeatmapMode").then((m) => ({ default: m.HeatmapMode })),
);

/** A mode that failed to load leaves the page as it is. */
class Quiet extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? null : this.props.children;
  }
}

/**
 * The heatmap mode's place in the app shell (ADR 0016). Only a browser marked as an admin's
 * loads its code, and only once the page has loaded; every other visitor loads none of it
 * and sends no extra request.
 */
export function AdminHeatmap() {
  const [admin] = useState(isUsageAdmin);
  if (!admin) return null;
  return (
    <Quiet>
      <Suspense fallback={null}>
        <HeatmapMode />
      </Suspense>
    </Quiet>
  );
}
