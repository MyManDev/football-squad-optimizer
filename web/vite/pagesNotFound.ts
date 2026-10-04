/**
 * The preview answers a missing file the way Cloudflare Pages does: with the closest
 * 404.html up the directory tree and status 404, and with the application shell only where
 * no such file exists, which is every client-side route (the site has no top-level
 * 404.html). Vite's preview answered every missing path with the shell and status 200, so
 * no local test met the 404 the live site serves for a document that is not published yet.
 */

import { existsSync, readFileSync, statSync } from "node:fs";
import { dirname, isAbsolute, join, relative, resolve } from "node:path";
import type { Plugin } from "vite";

const NOT_FOUND_PAGE = "404.html";

function inside(root: string, path: string): boolean {
  const offset = relative(root, path);
  return !offset.startsWith("..") && !isAbsolute(offset);
}

/**
 * The 404.html Pages would answer a request path with, or null when the path names a
 * file or directory that exists, lies outside the root, or has no 404.html above it.
 */
export function closestNotFound(root: string, pathname: string): string | null {
  const target = resolve(root, `.${pathname}`);
  if (!inside(root, target) || existsSync(target)) return null;
  for (let directory = dirname(target); inside(root, directory); directory = dirname(directory)) {
    const page = join(directory, NOT_FOUND_PAGE);
    if (existsSync(page) && statSync(page).isFile()) return page;
    if (directory === root) break;
  }
  return null;
}

/**
 * The request's path under the site base, decoded, or null when it is not under the base.
 * Vite keeps the base percent-encoded, so the encoded path is compared before decoding.
 */
export function sitePath(url: string, base: string): string | null {
  const pathname = new URL(url, "http://preview.invalid").pathname;
  const prefix = base.endsWith("/") ? base : `${base}/`;
  if (!pathname.startsWith(prefix)) return null;
  try {
    return `/${decodeURIComponent(pathname.slice(prefix.length))}`;
  } catch {
    return null;
  }
}

export function pagesNotFound(): Plugin {
  return {
    name: "squadopt:pages-not-found",
    configurePreviewServer(server) {
      const root = resolve(server.config.root, server.config.build.outDir);
      server.middlewares.use((request, response, next) => {
        if (request.method !== "GET" && request.method !== "HEAD") return next();
        const pathname = sitePath(request.url ?? "/", server.config.base);
        const page = pathname === null ? null : closestNotFound(root, pathname);
        if (page === null) return next();
        response.statusCode = 404;
        response.setHeader("Content-Type", "text/html; charset=utf-8");
        response.setHeader("Cache-Control", "no-store");
        response.end(request.method === "HEAD" ? undefined : readFileSync(page));
      });
    },
  };
}
