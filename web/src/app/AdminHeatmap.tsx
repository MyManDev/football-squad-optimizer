import { Component, lazy, Suspense, useEffect, useState, type ReactNode } from "react";

import { isUsageAdmin, USAGE_ADMIN_EVENT, USAGE_ADMIN_KEY } from "../data/usageAdminFlag";

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
 *
 * A browser can become an admin's while the app is open: the admin page marks it after its
 * first report, in this tab or another. The shell listens for that, so the mode appears without
 * a reload; a browser that was never marked still loads and asks nothing.
 */
export function AdminHeatmap() {
  const [admin, setAdmin] = useState(isUsageAdmin);
  useEffect(() => {
    if (admin) return undefined;
    const recheck = () => {
      if (isUsageAdmin()) setAdmin(true);
    };
    const fromOtherTab = (event: StorageEvent) => {
      if (event.key === USAGE_ADMIN_KEY) recheck();
    };
    window.addEventListener(USAGE_ADMIN_EVENT, recheck);
    window.addEventListener("storage", fromOtherTab);
    return () => {
      window.removeEventListener(USAGE_ADMIN_EVENT, recheck);
      window.removeEventListener("storage", fromOtherTab);
    };
  }, [admin]);
  if (!admin) return null;
  return (
    <Quiet>
      <Suspense fallback={null}>
        <HeatmapMode />
      </Suspense>
    </Quiet>
  );
}
