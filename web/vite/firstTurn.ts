/**
 * The first network turn starts with the document, not with the application's code.
 *
 * Measured on the live site at phone size with a cold cache: the scripts had arrived at
 * about 560 ms, and the league directory, the one read every page waits for, was asked for
 * at about 700 ms once React had mounted the gate; the compute service's first call then
 * paid a new connection to its origin on top. Both are known before any script runs, so
 * index.html asks for them in its head: the directory as a fetch preload at the address the
 * gate reads it from (`directory.ts`), which the read then joins instead of starting; and a
 * preconnect to the compute service's origin where the build names one, so the first call
 * finds the connection open.
 */

import type { HtmlTagDescriptor, Plugin } from "vite";

export const DIRECTORY_DOCUMENT = "data/leagues.json";

/** The site base with exactly one trailing slash, as `import.meta.env.BASE_URL` has it. */
function withSlash(base: string): string {
  return base.endsWith("/") ? base : `${base}/`;
}

/**
 * The head tags for a site base and a compute service origin ("" or undefined for none).
 * The preload's `crossorigin` matches the gate's `fetch`, which sends no credentials to its
 * own origin either way, so the browser hands the preloaded response to that read.
 */
export function firstTurnTags(base: string, apiOrigin: string | undefined): HtmlTagDescriptor[] {
  const tags: HtmlTagDescriptor[] = [
    {
      tag: "link",
      attrs: {
        rel: "preload",
        as: "fetch",
        href: `${withSlash(base)}${DIRECTORY_DOCUMENT}`,
        crossorigin: true,
      },
      injectTo: "head",
    },
  ];
  const origin = (apiOrigin ?? "").trim().replace(/\/+$/, "");
  if (/^https?:\/\/[^/]+$/.test(origin)) {
    tags.push({
      tag: "link",
      attrs: { rel: "preconnect", href: origin, crossorigin: true },
      injectTo: "head",
    });
  }
  return tags;
}

export function firstTurn(): Plugin {
  let base = "/";
  let apiOrigin: string | undefined;
  return {
    name: "squadopt:first-turn",
    configResolved(config) {
      base = config.base;
      apiOrigin = config.env.VITE_ADVICE_API_ORIGIN as string | undefined;
    },
    transformIndexHtml() {
      return firstTurnTags(base, apiOrigin);
    },
  };
}
