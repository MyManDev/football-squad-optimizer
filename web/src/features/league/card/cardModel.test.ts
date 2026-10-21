import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { mockEntryAdviceEnvelope, mockEntrySquadEnvelopes } from "../../../fixtures/league";
import {
  CARD_COLOURS,
  CARD_WIDTH,
  cardData,
  fitText,
  squadCardSvg,
  textWidth,
  type CardCopy,
  type CardField,
  type CardPlayer,
} from "./cardModel";

const ENTRY = 35249001;
const copy: CardCopy = {
  title: (gameweek) => `Gameweek ${gameweek} plan`,
  captain: "Captain",
  viceCaptain: "Vice-captain",
  captainMark: "C",
  viceMark: "V",
  bench: "Bench",
  transfers: "Transfers",
  noTransfers: "No transfers",
  hit: (points) => `${points} hit points`,
  expectedPoints: "Expected points",
  chip: "Chip",
  chipNames: { "3xc": "Triple Captain" },
  formatPoints: (value) => value.toFixed(2),
};

function plan() {
  const view = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1).payload;
  const squad = mockEntrySquadEnvelopes[ENTRY]!.payload;
  return { view, squad, data: cardData(view, squad)! };
}

const svgOf = (fields: CardField[]) => squadCardSvg(plan().data, new Set(fields), copy);

const starter = (id: number, name: string, position: CardPlayer["position"]): CardPlayer => ({
  id,
  name,
  position,
  team: "ARS",
});

/** A 3-5-2 whose midfield is the given row, so the five plates share one line of the pitch. */
function elevenWithMidfield(names: string[]): CardPlayer[] {
  return [
    starter(1, "Raya", "GK"),
    starter(2, "Gabriel", "DEF"),
    starter(3, "Saliba", "DEF"),
    starter(4, "Timber", "DEF"),
    ...names.map((name, index) => starter(10 + index, name, "MID")),
    starter(20, "Haaland", "FWD"),
    starter(21, "Isak", "FWD"),
  ];
}

const parse = (svg: string) => new DOMParser().parseFromString(svg, "image/svg+xml");
const num = (element: Element | null, name: string) => Number(element?.getAttribute(name));

/** Each name plate as drawn: its box, the name on it and the disc on its corner, if any. */
function platesOf(svg: string) {
  return Array.from(parse(svg).querySelectorAll("g.plate"), (plate) => {
    const rect = plate.querySelector("rect");
    const [name, mark] = Array.from(plate.querySelectorAll("text"));
    const disc = plate.querySelector("circle");
    return {
      x: num(rect, "x"),
      y: num(rect, "y"),
      width: num(rect, "width"),
      height: num(rect, "height"),
      name: name?.textContent ?? "",
      size: num(name ?? null, "font-size"),
      mark: mark?.textContent ?? null,
      disc: disc === null ? null : { cx: num(disc, "cx"), cy: num(disc, "cy"), r: num(disc, "r") },
    };
  });
}

/** Where each line of text reaches across the card, by the same estimate the card fits by. */
function linesOf(svg: string) {
  return Array.from(parse(svg).querySelectorAll("text"), (line) => {
    const value = line.textContent ?? "";
    const width = textWidth(value, num(line, "font-size"), num(line, "font-weight"));
    const x = num(line, "x");
    const anchor = line.getAttribute("text-anchor");
    const left = anchor === "middle" ? x - width / 2 : anchor === "end" ? x - width : x;
    return { value, size: num(line, "font-size"), left, right: left + width };
  });
}

describe("cardData", () => {
  it("reads the plan's eleven, bench, captain and moves", () => {
    const { view, data } = plan();
    expect(data.starters).toHaveLength(11);
    expect(data.bench).toHaveLength(4);
    expect(data.captain?.id).toBe(view.captain!.player_id);
    expect(data.captain?.name).toBe(view.captain!.short_name || view.captain!.name);
    expect(data.gameweek).toBe(view.gameweek);
  });

  it("gives no card for a plan without a one-week eleven", () => {
    const { view, squad } = plan();
    expect(cardData({ ...view, starting_xi: null }, squad)).toBeNull();
    expect(cardData({ ...view, captain: null }, squad)).toBeNull();
  });
});

describe("squadCardSvg", () => {
  it("draws the team, the eleven with its armbands and the bench, without transfers", () => {
    const { data } = plan();
    const { svg } = svgOf(["team", "lineup", "captain"]);
    expect(svg).toContain(`Gameweek ${data.gameweek} plan`);
    if (data.teamName) expect(svg).toContain(data.teamName);
    for (const starter of data.starters) expect(svg).toContain(`>${starter.name}<`);
    expect(svg).toContain(">Bench<");
    expect(svg).toContain(`Captain: ${data.captain!.name}`);
    expect(svg).toContain(">C<");
    expect(svg).not.toContain(">Transfers<");
    expect(svg).not.toContain(">Expected points<");
  });

  it("draws only the transfers and the expected points when those two are picked", () => {
    const { data } = plan();
    const { svg } = svgOf(["transfers", "points"]);
    expect(svg).toContain(">Transfers<");
    if (data.moves.length === 0) expect(svg).toContain(">No transfers<");
    for (const move of data.moves) {
      expect(svg).toContain(`>${move.out}<`);
      expect(svg).toContain(`>${move.in}<`);
    }
    if (data.expectedPoints !== null) {
      expect(svg).toContain(">Expected points<");
      expect(svg).toContain(`>${data.expectedPoints.toFixed(2)}<`);
    }
    const inMoves = new Set(data.moves.flatMap((move) => [move.out, move.in]));
    const starter = data.starters.find((player) => !inMoves.has(player.name))!;
    expect(svg).not.toContain(`>${starter.name}<`);
    if (data.teamName) expect(svg).not.toContain(data.teamName);
    expect(svg).not.toContain(">Bench<");
  });

  it("grows with the fields picked and keeps the gameweek on every card", () => {
    const small = svgOf([]);
    const full = svgOf(["team", "lineup", "captain", "transfers", "points"]);
    expect(full.height).toBeGreaterThan(small.height);
    expect(small.svg).toContain("Gameweek");
    expect(small.width).toBe(1080);
  });

  it("escapes names, so a name cannot break the image", () => {
    const { data } = plan();
    const tricky = { ...data, teamName: `A&B <Rovers> "x"` };
    const { svg } = squadCardSvg(tricky, new Set<CardField>(["team"]), copy);
    expect(svg).toContain("A&amp;B &lt;Rovers&gt; &quot;x&quot;");
    expect(svg).not.toContain("<Rovers>");
  });

  it("names the hit with the transfers and the chip in the header, whatever the fields", () => {
    const { data } = plan();
    const tripled = { ...data, hitPoints: 4, chip: "3xc" as const };
    const transfers = squadCardSvg(tripled, new Set<CardField>(["transfers"]), copy).svg;
    expect(transfers).toContain(">4 hit points<");
    expect(transfers).toContain(">Chip: Triple Captain<");
    const armbands = squadCardSvg(tripled, new Set<CardField>(["lineup", "captain"]), copy).svg;
    expect(armbands).toContain(">Chip: Triple Captain<");
    expect(armbands).not.toContain("hit points");
    expect(svgOf(["lineup", "captain"]).svg).not.toContain("Chip:");
  });

  it("puts the armbands on the captain's and the vice's plates by player, not by name", () => {
    // Alex Palmer keeps goal while Cole Palmer captains: one plate takes the C, not both.
    const eleven = elevenWithMidfield(["Palmer", "Rice", "Saka", "Merino", "Zubimendi"]);
    eleven[0] = { id: 112520, name: "Palmer", position: "GK", team: "IPS" };
    eleven[4] = { ...eleven[4]!, id: 244851, team: "CHE" };
    const data = {
      ...plan().data,
      starters: eleven,
      captain: eleven[4]!,
      viceCaptain: eleven[5]!,
    };
    const { svg } = squadCardSvg(data, new Set<CardField>(["lineup", "captain"]), copy);
    expect(svg.match(/>Palmer</g)).toHaveLength(2);
    expect(svg.match(/>C</g)).toHaveLength(1);
    expect(svg.match(/>V</g)).toHaveLength(1);
    // The goalkeeper's plate comes first and carries no armband; the C follows Cole's name.
    expect(svg.indexOf(">C<")).toBeGreaterThan(svg.lastIndexOf(">Palmer<"));
  });

  it("sets a long row of five on plates that never overlap, each name in full", () => {
    const row = ["Maitland-Niles", "Dewsbury-Hall", "Gibbs-White", "Szoboszlai", "Calvert-Lewin"];
    const eleven = elevenWithMidfield(row);
    // The captain and the vice side by side, so their discs sit on neighbouring plates.
    const data = {
      ...plan().data,
      starters: eleven,
      captain: eleven[4]!,
      viceCaptain: eleven[5]!,
    };
    const plates = platesOf(
      squadCardSvg(data, new Set<CardField>(["lineup", "captain"]), copy).svg,
    );
    expect(plates).toHaveLength(11);

    const rows = new Map<number, typeof plates>();
    for (const plate of plates) rows.set(plate.y, [...(rows.get(plate.y) ?? []), plate]);
    const midfield = [...rows.values()].find((line) => line.length === 5)!;
    expect(midfield.map((plate) => plate.name)).toEqual(row);
    expect(midfield.map((plate) => plate.mark)).toEqual(["C", "V", null, null, null]);
    for (const line of rows.values()) {
      const sorted = [...line].sort((a, b) => a.x - b.x);
      sorted.slice(1).forEach((plate, index) => {
        expect(sorted[index]!.x + sorted[index]!.width).toBeLessThan(plate.x);
      });
      // One size across the row, never under the floor.
      expect(new Set(line.map((plate) => plate.size)).size).toBe(1);
      expect(line[0]!.size).toBeGreaterThanOrEqual(20);
    }
    const rowTops = [...rows.keys()].sort((a, b) => a - b);
    for (const plate of plates) {
      // The name keeps 8 px clear of each edge of its plate.
      expect(textWidth(plate.name, plate.size)).toBeLessThanOrEqual(plate.width - 16);
      if (plate.disc === null) continue;
      // The disc stays inside its plate's width and clear of the plate on the row above.
      expect(plate.disc.cx - plate.disc.r).toBeGreaterThanOrEqual(plate.x);
      expect(plate.disc.cx + plate.disc.r).toBeLessThanOrEqual(plate.x + plate.width);
      const above = rowTops.filter((top) => top < plate.y).at(-1);
      if (above !== undefined) {
        expect(plate.disc.cy - plate.disc.r).toBeGreaterThan(above + plate.height);
      }
    }
  });

  it("cuts a name too long for its plate even at the smallest size, with an ellipsis", () => {
    const long = "Wolfeschlegelsteinhausenbergerdorff";
    const eleven = elevenWithMidfield(["Saka", long, "Rice", "Ødegaard", "Merino"]);
    const data = { ...plan().data, starters: eleven };
    const plates = platesOf(squadCardSvg(data, new Set<CardField>(["lineup"]), copy).svg);
    const cut = plates.find((plate) => plate.name.startsWith("Wolfe"))!;
    expect(cut.name).toMatch(/^Wolfe\S+…$/u);
    expect(cut.size).toBe(20);
    expect(textWidth(cut.name, cut.size)).toBeLessThanOrEqual(cut.width - 16);
    expect(plates.find((plate) => plate.name === "Saka")!.size).toBe(20);
  });

  it("keeps every line inside the card's margins, however long the names", () => {
    const long = "Featherstonehaugh Wolfeschlegelsteinhausenbergerdorff Montmorency";
    const manager = "MAXIMILIAN ".repeat(6).slice(0, 64);
    const { data } = plan();
    const eleven = elevenWithMidfield([
      "Maitland-Niles",
      "Dewsbury-Hall",
      "Gibbs-White",
      "Szoboszlai",
      "Calvert-Lewin",
    ]);
    const tall = {
      ...data,
      teamName: `${long} ${long}`,
      managerName: manager,
      starters: eleven,
      bench: [eleven[4]!, eleven[5]!, eleven[7]!, eleven[8]!],
      captain: { ...eleven[4]!, name: long },
      viceCaptain: { ...eleven[5]!, name: long },
      moves: [{ out: long, in: long }],
      hitPoints: 12,
      chip: "3xc" as const,
      expectedPoints: 56.55,
    };
    const all = new Set<CardField>(["team", "lineup", "captain", "transfers", "points"]);
    const lines = linesOf(squadCardSvg(tall, all, copy).svg);
    for (const line of lines) {
      expect(line.left, line.value).toBeGreaterThanOrEqual(56);
      expect(line.right, line.value).toBeLessThanOrEqual(CARD_WIDTH - 56);
    }
    // A 64-letter manager name ran past the card's edge: it shrinks to fit, and a team name
    // too long even at its smallest size is cut.
    const managerLine = lines.find((line) => line.value.startsWith("MAXIMILIAN"))!;
    expect(managerLine.value).toBe(manager);
    expect(managerLine.size).toBeLessThan(28);
    const teamLine = lines.find((line) => line.value.startsWith("Featherstonehaugh"))!;
    expect(teamLine.value).toMatch(/^Featherstonehaugh .*…$/u);
    expect(teamLine.size).toBe(27);
    // The name leaving the squad stops short of the arrow between the two names.
    const arrow = lines.find((line) => line.value === "→")!;
    const out = lines.filter((line) => line.value.startsWith("Feather") && line.left === 84);
    expect(out).toHaveLength(1);
    expect(out[0]!.right).toBeLessThan(arrow.left);
  });

  it("ends the grass at the pitch, so the bench row sits on the board", () => {
    const doc = parse(svgOf(["lineup"]).svg);
    const pitch = doc.querySelector(`rect[fill="${CARD_COLOURS["--color-pitch"]}"]`)!;
    const bottom = num(pitch, "y") + num(pitch, "height");
    const stripes = doc.querySelectorAll(`rect[fill="${CARD_COLOURS["--color-pitch-2"]}"]`);
    expect(stripes.length).toBeGreaterThan(0);
    for (const stripe of stripes) {
      expect(num(stripe, "y") + num(stripe, "height")).toBeLessThanOrEqual(bottom);
    }
    const bench = Array.from(doc.querySelectorAll("text")).find(
      (line) => line.textContent === "Bench",
    )!;
    expect(num(bench, "y") - num(bench, "font-size")).toBeGreaterThanOrEqual(bottom);
  });
});

describe("fitText", () => {
  it("keeps a line that fits, shrinks one that does not, and cuts it only at the floor", () => {
    expect(fitText("Saka", 200, 28, 20)).toEqual({ value: "Saka", size: 28 });
    const shrunk = fitText("Maitland-Niles", 160, 28, 20);
    expect(shrunk.value).toBe("Maitland-Niles");
    expect(shrunk.size).toBeLessThan(28);
    expect(textWidth(shrunk.value, shrunk.size)).toBeLessThanOrEqual(160);
    const cut = fitText("Maitland-Niles", 100, 28, 20);
    expect(cut.size).toBe(20);
    expect(cut.value).toMatch(/^Mait\S*…$/u);
    expect(textWidth(cut.value, 20)).toBeLessThanOrEqual(100);
  });

  it("reads Turkish letters at their base letter's width", () => {
    expect(textWidth("Kadıoğlu", 28)).toBe(textWidth("Kadioglu", 28));
    expect(textWidth("İŞÇ", 28)).toBe(textWidth("ISC", 28));
  });
});

describe("the card's colours", () => {
  const tokens = readFileSync(join(__dirname, "../../../design/tokens.css"), "utf-8").replace(
    /\/\*[\s\S]*?\*\//g,
    "",
  );
  const root = tokens.match(/:root\s*\{([\s\S]*?)\n\}/)?.[1] ?? "";

  it.each(Object.entries(CARD_COLOURS))("draws %s as tokens.css sets it", (token, value) => {
    const set = root.match(new RegExp(`\\s${token}:\\s*(#[0-9a-fA-F]{6});`))?.[1];
    expect(set?.toLowerCase()).toBe(value);
  });
});
