import { useEffect } from "react";
import { useLocation } from "react-router";

import { recordUsage } from "../data/usage";

/** Tells the usage record each address the router reaches; a new query string is not one. */
export function UsagePageOpen() {
  const { pathname } = useLocation();
  useEffect(() => recordUsage({ step: "open" }), [pathname]);
  return null;
}
