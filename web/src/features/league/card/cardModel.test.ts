import { describe, expect, it } from "vitest";

import { mockEntryAdviceEnvelope, mockEntrySquadEnvelopes } from "../../../fixtures/league";
import {
  cardData,
  squadCardSvg,
  type CardCopy,
  type CardField,
  type CardPlayer,
} from "./cardModel";

const ENTRY = 35249001;
const copy: CardCopy = {
  title: (gameweek) => `Gameweek ${gameweek} plan`,
  captain: "Captain",
  viceCaptain: "Vice",
  bench: "Bench",
  transfers: "Transfers",
  noTransfers: "No transfers",
  hit: (points) => `Hit ${points}`,
  expectedPoints: "Expected points",
  chip: (name) => `Chip: ${name}`,
  chipNames: { "3xc": "Triple Captain" },
  formatPoints: (value) => value.toFixed(1),
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
      expect(svg).toContain(`>${data.expectedPoints.toFixed(1)}<`);
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

  it("names the hit and the chip with the transfers when the plan has them", () => {
    const { data } = plan();
    const { svg } = squadCardSvg(
      { ...data, hitPoints: 4, chip: "3xc" },
      new Set<CardField>(["transfers"]),
      copy,
    );
    expect(svg).toContain(">Hit 4.0<");
    expect(svg).toContain(">Chip: Triple Captain<");
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
});
