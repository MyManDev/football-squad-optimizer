import "@testing-library/jest-dom/vitest";

import { afterEach } from "vitest";

// A waiting advice job is remembered in sessionStorage so a reload can resume it. One
// test's unfinished wait must not be the next test's resumed one.
afterEach(() => {
  if (typeof sessionStorage !== "undefined") sessionStorage.clear();
});
