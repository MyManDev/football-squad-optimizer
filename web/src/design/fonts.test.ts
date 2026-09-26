/**
 * The site serves its own type: fonts.css declares the faces, the build copies the files into
 * assets/, and no reader's browser asks a font host for anything. This holds fonts.css to the
 * packages it points into (every face names a woff2 file the package ships, with the unicode
 * range the package publishes for that subset) and holds index.html and the entry to that
 * arrangement, so the remote stylesheet cannot come back beside the local one.
 */
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const WEB = join(__dirname, "../..");
const read = (relative: string) => readFileSync(join(WEB, relative), "utf-8");

/** The faces the stylesheets ask for; each comes as latin-ext, then latin. */
const FACES = [
  ["Barlow Semi Condensed", 700],
  ["Barlow Semi Condensed", 800],
  ["IBM Plex Sans", 400],
  ["IBM Plex Sans", 500],
  ["IBM Plex Sans", 600],
  ["IBM Plex Mono", 500],
  ["IBM Plex Mono", 600],
] as const;
const SUBSETS = ["latin-ext", "latin"] as const;

type Face = Record<"family" | "style" | "weight" | "display" | "src" | "range", string>;

function declaredFaces(css: string): Face[] {
  const bodies = [...css.replace(/\/\*[\s\S]*?\*\//g, "").matchAll(/@font-face\s*\{([^}]*)\}/g)];
  return bodies.map(([, body]) => {
    const value = (name: string) =>
      (body!.match(new RegExp(`${name}:\\s*([^;]+);`))?.[1] ?? "").replace(/\s+/g, " ").trim();
    return {
      family: value("font-family").replace(/"/g, ""),
      style: value("font-style"),
      weight: value("font-weight"),
      display: value("font-display"),
      src: value("src"),
      range: value("unicode-range"),
    };
  });
}

const faces = declaredFaces(read("src/design/fonts.css"));
const SRC =
  /^url\("@fontsource\/([a-z-]+)\/files\/\1-(latin-ext|latin)-(\d{3})-normal\.woff2"\) format\("woff2"\)$/;

describe("self-hosted fonts", () => {
  it("declares each face the stylesheets ask for, in latin-ext and latin, and no other", () => {
    const expected = FACES.flatMap(([family, weight]) =>
      SUBSETS.map((subset) => `${family} ${weight} ${subset}`),
    );
    expect(
      faces.map((face) => `${face.family} ${face.weight} ${face.src.match(SRC)?.[2]}`),
    ).toEqual(expected);
  });

  it("points every face at a woff2 file its package ships, with the package's range", () => {
    for (const face of faces) {
      const match = face.src.match(SRC);
      expect(match, face.src).not.toBeNull();
      const [, pkg, subset, weight] = match!;
      expect(weight).toBe(face.weight);
      const packageDir = join(WEB, "node_modules/@fontsource", pkg!);
      expect(existsSync(join(packageDir, "files", `${pkg}-${subset}-${weight}-normal.woff2`))).toBe(
        true,
      );
      const ranges = JSON.parse(readFileSync(join(packageDir, "unicode.json"), "utf-8")) as Record<
        string,
        string
      >;
      expect(face.range.replace(/\s/g, ""), `${pkg} ${subset} ${weight}`).toBe(ranges[subset!]);
    }
  });

  it("draws every face upright and shows fallback text until the file arrives", () => {
    for (const face of faces) {
      expect(face.style).toBe("normal");
      expect(face.display).toBe("swap");
    }
  });

  it("is imported by the entry, and index.html names no font host", () => {
    expect(read("src/main.tsx")).toContain('import "./design/fonts.css";');
    const html = read("index.html");
    expect(html).not.toMatch(/fonts\.(googleapis|gstatic)\.com/);
    expect(html).not.toMatch(/<link[^>]+href="https?:\/\//);
  });
});
