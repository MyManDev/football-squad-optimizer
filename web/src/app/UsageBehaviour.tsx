import { useEffect } from "react";
import { useLocation } from "react-router";

import { watchUsageBehaviour } from "../data/usageBehaviour";

/**
 * Starts the usage record's behaviour listeners once (ADR 0015) and tells them each address
 * the router reaches, which begins a new page view; a new query string is not one.
 */
export function UsageBehaviour() {
  const { pathname } = useLocation();
  useEffect(() => watchUsageBehaviour(), [pathname]);
  return null;
}
