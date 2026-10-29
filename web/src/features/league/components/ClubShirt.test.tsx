/**
 * The player's shirt: the club's colours with initials that read at 4.5:1 on the body, one
 * shared colour for every goalkeeper that no club wears, a blank shirt for a club with no
 * colours, and nothing a screen reader hears, since the plate already names the player and
 * the club.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { AA, contrastRatio } from "../../../design/contrastRatio";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import type { Language } from "../../../i18n/messages";
import { CLUB_COLOURS } from "../../../lib/clubs";
import { ClubShirt } from "./ClubShirt";
import { clubPlate, PLATE_INK, PLATE_WHITE } from "./pitchLook";

/** The twenty clubs of the 2026-27 season, by the code the fixture list prints. */
const SEASON_CODES = [
  "ARS",
  "AVL",
  "BHA",
  "BOU",
  "BRE",
  "CHE",
  "COV",
  "CRY",
  "EVE",
  "FUL",
  "HUL",
  "IPS",
  "LEE",
  "LIV",
  "MCI",
  "MUN",
  "NEW",
  "NFO",
  "SUN",
  "TOT",
] as const;

const uncommented = (file: string) =>
  readFileSync(join(__dirname, file), "utf-8").replace(/\/\*[\s\S]*?\*\//g, "");

/** A colour token's value on tokens.css's :root. */
function token(name: string): string {
  const root =
    uncommented("../../../design/tokens.css").match(/:root\s*\{([\s\S]*?)\n\}/)?.[1] ?? "";
  const value = root.match(new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6});`))?.[1];
  if (value === undefined) throw new Error(`${name} is not a six-digit hex colour on :root`);
  return value;
}

/** The declarations of one rule in the shirt's stylesheet, whitespace folded. */
const rule = (selector: string) =>
  uncommented("ClubShirt.module.css")
    .match(new RegExp(String.raw`(^|\n)${selector.replace(/[.[\]"]/g, "\\$&")}\s*\{([^}]*)\}`))?.[2]
    ?.replace(/\s+/g, " ")
    .trim();

function shirt(props: Partial<Parameters<typeof ClubShirt>[0]> = {}, language: Language = "tr") {
  const { container } = render(
    <LanguageProvider initialLanguage={language}>
      <ClubShirt code="TOT" name="Bukayo Saka" size="large" {...props} />
    </LanguageProvider>,
  );
  return container.querySelector("svg")!;
}

const colour = (svg: SVGSVGElement, name: string) => svg.style.getPropertyValue(name);

afterEach(cleanup);

describe("a club's shirt", () => {
  it.each(SEASON_CODES)("is drawn in %s's two colours, its initials 4.5:1 on its body", (code) => {
    const svg = shirt({ code });
    const { primary, secondary } = CLUB_COLOURS[code]!;
    const plate = clubPlate(code)!;
    expect(svg).toHaveAttribute("data-shirt", "club");
    // The body is filled as the club's plate is, and the trim takes the other colour.
    expect(colour(svg, "--shirt-body")).toBe(plate.fill);
    expect(colour(svg, "--shirt-trim")).toBe(plate.colour === "primary" ? secondary : primary);
    expect([PLATE_INK, PLATE_WHITE]).toContain(colour(svg, "--shirt-ink"));
    expect(
      contrastRatio(colour(svg, "--shirt-ink"), colour(svg, "--shirt-body")),
    ).toBeGreaterThanOrEqual(AA);
  });

  it("has its body in the club's first colour wherever its initials read on it", () => {
    const firsts = SEASON_CODES.filter((code) => clubPlate(code)!.colour === "primary");
    for (const code of firsts)
      expect(colour(shirt({ code }), "--shirt-body"), code).toBe(CLUB_COLOURS[code]!.primary);
    // Only Arsenal's and Sunderland's reds read under 4.5:1 with ink and with white (4.49
    // and 4.48 with white), so only their shirts are white with red sleeves and collar.
    expect(SEASON_CODES.filter((code) => !firsts.includes(code))).toEqual(["ARS", "SUN"]);
    cleanup();
    const arsenal = shirt({ code: "ARS" });
    expect(colour(arsenal, "--shirt-body")).toBe("#FFFFFF");
    expect(colour(arsenal, "--shirt-trim")).toBe("#EF0107");
    expect(colour(arsenal, "--shirt-ink")).toBe(PLATE_INK);
  });

  it.each([null, undefined, "", "XYZ"])(
    "is a blank shirt for a club with no colours (%s)",
    (code) => {
      const svg = shirt({ code });
      expect(svg).toHaveAttribute("data-shirt", "blank");
      expect(colour(svg, "--shirt-body")).toBe("");
      expect(rule('.shirt[data-shirt="blank"]')).toBe(
        "--shirt-body: var(--color-chip); --shirt-trim: var(--color-chip); --shirt-ink: var(--color-chip-text);",
      );
      expect(
        contrastRatio(token("--color-chip-text"), token("--color-chip")),
      ).toBeGreaterThanOrEqual(AA);
    },
  );
});

describe("a goalkeeper's shirt", () => {
  it.each([...SEASON_CODES, "XYZ"])("is the keepers' one colour, not %s's", (code) => {
    const svg = shirt({ code, keeper: true });
    expect(svg).toHaveAttribute("data-shirt", "keeper");
    // No club colour is written on it: the stylesheet gives every keeper the same shirt.
    expect(colour(svg, "--shirt-body")).toBe("");
    expect(colour(svg, "--shirt-trim")).toBe("");
  });

  it("is a colour no club wears, with ink initials at 4.5:1", () => {
    expect(rule('.shirt[data-shirt="keeper"]')).toBe(
      "--shirt-body: var(--color-keeper); --shirt-trim: var(--color-text); --shirt-ink: var(--color-text);",
    );
    const keeper = token("--color-keeper").toLowerCase();
    const worn = Object.values(CLUB_COLOURS).flatMap(({ primary, secondary }) => [
      primary.toLowerCase(),
      secondary.toLowerCase(),
    ]);
    expect(worn).not.toContain(keeper);
    // Nor the page's lime, which marks YENİ and the armband, nor either grass.
    for (const other of ["--color-lime", "--color-pitch", "--color-pitch-2"])
      expect(token(other).toLowerCase()).not.toBe(keeper);
    expect(contrastRatio(token("--color-text"), keeper)).toBeGreaterThanOrEqual(AA);
  });
});

describe("the initials", () => {
  const letters = (name: string, language: Language = "tr") =>
    shirt({ name }, language).querySelector("text")?.textContent ?? null;

  it.each([
    ["Bukayo Saka", "BS"],
    ["Erling Haaland", "EH"],
    ["Trent Alexander-Arnold", "TA"],
    ["Gabriel dos Santos Magalhães", "GM"],
    ["N'Golo Kanté", "NK"],
    ["Martin Ødegaard", "MØ"],
    ["İlkay Gündoğan", "İG"],
    ["Çağlar Söyüncü", "ÇS"],
    ["Ferdi Kadıoğlu", "FK"],
    ["  Bukayo   Saka  ", "BS"],
  ])("of %s are %s", (name, expected) => {
    expect(letters(name)).toBe(expected);
  });

  it("are one letter for a single name", () => {
    expect(letters("Rodri")).toBe("R");
    expect(letters("'Rodri'")).toBe("R");
    expect(letters("Ødegaard")).toBe("Ø");
  });

  it("keep a letter written with a combining accent whole", () => {
    expect(letters("Martin O\u0308degaard")).toBe("MÖ");
  });

  it("raise a lower-case letter by the page language's rules", () => {
    expect(letters("ilkay gündoğan", "tr")).toBe("İG");
    expect(letters("ilkay gündoğan", "en")).toBe("IG");
    expect(letters("ılgaz şahin", "tr")).toBe("IŞ");
  });

  it("are drawn only on the large shirt, in 12 px type on a 1:1 grid", () => {
    expect(shirt({ size: "small" }).querySelector("text")).toBeNull();
    const large = shirt();
    expect(large.getAttribute("viewBox")).toBe("0 0 32 28");
    expect(rule(".large")).toBe("width: 32px; height: 28px;");
    // --step--2 is the page's 12 px floor.
    expect(rule(".initials")).toContain("font-size: var(--step--2);");
    expect(uncommented("../../../design/tokens.css")).toContain("--step--2: 0.75rem;");
  });

  it("are left off a name with no letters", () => {
    expect(letters("")).toBeNull();
    expect(letters("  - ")).toBeNull();
  });
});

describe("as decoration", () => {
  it.each(["small", "large"] as const)(
    "the %s shirt is hidden from assistive technology",
    (size) => {
      const svg = shirt({ size });
      expect(svg).toHaveAttribute("aria-hidden", "true");
      expect(svg).toHaveAttribute("focusable", "false");
      expect(svg).not.toHaveAttribute("role");
      // No <title> or title attribute: the plate's title is the player's name, and the pitch
      // finds each plate by it.
      expect(svg.querySelector("title")).toBeNull();
      expect(svg.querySelector("[title]")).toBeNull();
    },
  );

  it("is outlined in ink unless the plate gives it its own text colour", () => {
    expect(rule(".outline")).toContain("stroke: var(--shirt-line, var(--color-board));");
    expect(rule(".outline")).toContain("vector-effect: non-scaling-stroke;");
  });
});
