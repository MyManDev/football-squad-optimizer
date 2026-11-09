import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const ASSETS = fileURLToPath(new URL("../dist/assets", import.meta.url));

/** The route only a build with a compute origin has: the bundler drops it from the others. */
const ORIGIN_ONLY_ROUTE = /path:\s*["'`]\/contribute["'`]/;

/** Whether the build under test names a compute origin; null when there is no build yet. */
export function builtWithAdviceOrigin(assets: string = ASSETS): boolean | null {
  if (!existsSync(assets)) return null;
  return readdirSync(assets)
    .filter((name) => name.endsWith(".js"))
    .some((name) => ORIGIN_ONLY_ROUTE.test(readFileSync(join(assets, name), "utf-8")));
}

/**
 * The specs read VITE_ADVICE_API_ORIGIN from this process and the pages have it from the
 * build, and the two need not agree: a dist/ left by a build with the variable, run from a
 * shell without it, failed specs that have nothing wrong with them (14 on 8 Nov). One
 * sentence about the build says more than those do.
 */
export function refuseMismatchedBuild(
  origin: string | undefined = process.env.VITE_ADVICE_API_ORIGIN,
): void {
  const built = builtWithAdviceOrigin();
  if (built === null || built === Boolean(origin)) return;
  throw new Error(
    built
      ? "dist/ was built with VITE_ADVICE_API_ORIGIN and this run does not set it. Run `npm run build` in this shell, or set the variable to the same origin."
      : "This run sets VITE_ADVICE_API_ORIGIN and dist/ was built without it. Run `npm run build` in this shell, or unset the variable.",
  );
}
