import "@testing-library/jest-dom/vitest";

import { afterEach } from "vitest";

import { resetSiteForwarderBudget } from "../features/league/forwarder/client";

// A waiting advice job is remembered in sessionStorage so a reload can resume it. One
// test's unfinished wait must not be the next test's resumed one.
afterEach(() => {
  if (typeof sessionStorage !== "undefined") sessionStorage.clear();
});

// The site's forwarder client counts its reads against the rate rule's window. One test's
// reads must not make the next test's wait for a turn.
afterEach(() => resetSiteForwarderBudget());
