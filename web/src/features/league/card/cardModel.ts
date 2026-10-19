/**
 * The shareable squad card (#1135 part 3): the plan on screen drawn as one image.
 *
 * `squadCardSvg` is pure: the plan's facts and the fields the member picked give one SVG
 * document, which the device turns into a PNG (`drawCard`). Nothing is fetched or uploaded.
 * Every value comes from the advice document the page already shows; the card adds no
 * figure of its own and no probability or caveat wording.
 */
import type { AdviceChip, AdvicePlayer, EntryAdvice, EntrySquad } from "../types";

export const CARD_FIELDS = ["team", "lineup", "captain", "transfers", "points"] as const;
export type CardField = (typeof CARD_FIELDS)[number];
export const DEFAULT_CARD_FIELDS: readonly CardField[] = ["team", "lineup", "captain", "transfers"];

type Position = AdvicePlayer["position"];

export interface CardPlayer {
  name: string;
  position: Position;
  team: string;
}

export interface SquadCardData {
  gameweek: number;
  teamName: string | null;
  managerName: string | null;
  starters: CardPlayer[];
  bench: CardPlayer[];
  captain: string | null;
  viceCaptain: string | null;
  moves: { out: string; in: string }[];
  hitPoints: number;
  expectedPoints: number | null;
  chip: AdviceChip | null;
}

export interface CardCopy {
  title: (gameweek: number) => string;
  captain: string;
  viceCaptain: string;
  bench: string;
  transfers: string;
  noTransfers: string;
  hit: (points: string) => string;
  expectedPoints: string;
  chip: (name: string) => string;
  chipNames: Record<string, string>;
  formatPoints: (value: number) => string;
}

const player = (value: AdvicePlayer): CardPlayer => ({
  name: value.short_name || value.name,
  position: value.position,
  team: value.team,
});

/** The card's facts from the shown plan, or null when the plan carries no one-week lineup. */
export function cardData(view: EntryAdvice, squad: EntrySquad): SquadCardData | null {
  if (!view.starting_xi || view.starting_xi.length !== 11 || !view.bench || !view.captain) {
    return null;
  }
  return {
    gameweek: view.gameweek,
    teamName: squad.entry.team_name,
    managerName: squad.entry.manager_name,
    starters: view.starting_xi.map(player),
    bench: view.bench.map(player),
    captain: view.captain.short_name || view.captain.name,
    viceCaptain: view.vice_captain ? view.vice_captain.short_name || view.vice_captain.name : null,
    moves: view.moves
      .filter((move) => move.player_out && move.player_in)
      .map((move) => ({
        out: move.player_out!.short_name || move.player_out!.name,
        in: move.player_in!.short_name || move.player_in!.name,
      })),
    hitPoints: view.transfer_hit_points ?? 0,
    expectedPoints:
      typeof view.expected_own_points === "number" && Number.isFinite(view.expected_own_points)
        ? view.expected_own_points
        : null,
    chip: view.chip ?? null,
  };
}

// The card's colours mirror tokens.css: the board, the pitch, the chip and the one accent.
const BOARD = "#10261a";
const BOARD_MUTED = "#cfe3d3";
const PITCH = "#3f8f58";
const PITCH_STRIPE = "#48995f";
const CHIP = "#ffffff";
const CHIP_TEXT = "#10261a";
const ACCENT = "#c6ff3d";
const OUT = "#c62828";
const IN = "#1e7b45";
const FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif";

export const CARD_WIDTH = 1080;
const PAD = 56;
const ROW = 104;
const LINE = 62;

const escape = (text: string) =>
  text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");

function text(
  x: number,
  y: number,
  value: string,
  { size = 32, weight = 600, fill = CHIP_TEXT, anchor = "start", tabular = false } = {},
): string {
  const numbers = tabular ? ' font-variant-numeric="tabular-nums"' : "";
  return `<text x="${x}" y="${y}" font-family="${FONT}" font-size="${size}" font-weight="${weight}" fill="${fill}" text-anchor="${anchor}"${numbers}>${escape(value)}</text>`;
}

function chip(cx: number, y: number, label: string, mark: string | null): string {
  const width = Math.min(220, Math.max(140, label.length * 19 + 40));
  const x = cx - width / 2;
  const badge =
    mark === null
      ? ""
      : `<circle cx="${x + width - 6}" cy="${y + 6}" r="22" fill="${ACCENT}"/>${text(x + width - 6, y + 16, mark, { size: 26, weight: 800, anchor: "middle" })}`;
  return `<rect x="${x}" y="${y}" width="${width}" height="56" rx="12" fill="${CHIP}"/>${text(cx, y + 38, label, { size: 28, anchor: "middle" })}${badge}`;
}

const ORDER: Position[] = ["GK", "DEF", "MID", "FWD"];

/** One SVG document of the card, with only the fields the member picked, in a fixed order. */
export function squadCardSvg(
  data: SquadCardData,
  fields: ReadonlySet<CardField>,
  copy: CardCopy,
): { svg: string; width: number; height: number } {
  const parts: string[] = [];
  let y = PAD;

  // The header always names the week, so a card never travels without its gameweek.
  parts.push(text(PAD, y + 44, copy.title(data.gameweek), { size: 48, weight: 800, fill: ACCENT }));
  y += 72;
  if (fields.has("team") && data.teamName) {
    parts.push(text(PAD, y + 34, data.teamName, { size: 36, weight: 700, fill: CHIP }));
    y += 46;
  }
  if (fields.has("team") && data.managerName) {
    parts.push(text(PAD, y + 34, data.managerName, { size: 28, weight: 500, fill: BOARD_MUTED }));
    y += 46;
  }
  const headerBottom = y + 16;

  const body: string[] = [];
  y = headerBottom + 32;
  if (fields.has("lineup")) {
    const pitchTop = y - 16;
    const rows = ORDER.map((position) => data.starters.filter((p) => p.position === position));
    rows.forEach((row) => {
      row.forEach((p, index) => {
        const cx = (CARD_WIDTH * (index + 1)) / (row.length + 1);
        const mark =
          fields.has("captain") && p.name === data.captain
            ? "C"
            : fields.has("captain") && p.name === data.viceCaptain
              ? "V"
              : null;
        body.push(chip(cx, y, p.name, mark));
      });
      y += ROW;
    });
    const pitchHeight = y - pitchTop;
    const stripes = Array.from({ length: Math.ceil(pitchHeight / 80) }, (_, index) =>
      index % 2
        ? `<rect x="0" y="${pitchTop + index * 80}" width="${CARD_WIDTH}" height="80" fill="${PITCH_STRIPE}"/>`
        : "",
    ).join("");
    body.unshift(
      `<rect x="0" y="${pitchTop}" width="${CARD_WIDTH}" height="${pitchHeight}" fill="${PITCH}"/>${stripes}`,
    );
    body.push(text(PAD, y + 34, copy.bench, { size: 26, weight: 700, fill: BOARD_MUTED }));
    body.push(
      text(PAD + 150, y + 34, data.bench.map((p) => p.name).join(" · "), {
        size: 28,
        weight: 500,
        fill: CHIP,
      }),
    );
    y += LINE + 8;
  }
  if (fields.has("captain") && data.captain !== null) {
    const line = data.viceCaptain
      ? `${copy.captain}: ${data.captain} · ${copy.viceCaptain}: ${data.viceCaptain}`
      : `${copy.captain}: ${data.captain}`;
    body.push(text(PAD, y + 34, line, { size: 32, weight: 700, fill: CHIP }));
    y += LINE;
  }
  if (fields.has("transfers")) {
    body.push(text(PAD, y + 34, copy.transfers, { size: 26, weight: 700, fill: BOARD_MUTED }));
    y += 52;
    if (data.moves.length === 0) {
      body.push(text(PAD, y + 34, copy.noTransfers, { size: 30, weight: 600, fill: CHIP }));
      y += LINE;
    }
    data.moves.forEach((move) => {
      body.push(`<rect x="${PAD}" y="${y + 6}" width="12" height="40" rx="3" fill="${OUT}"/>`);
      body.push(text(PAD + 28, y + 38, move.out, { size: 30, weight: 600, fill: CHIP }));
      body.push(
        text(CARD_WIDTH / 2 - 10, y + 38, "→", { size: 30, fill: BOARD_MUTED, anchor: "middle" }),
      );
      body.push(
        `<rect x="${CARD_WIDTH / 2 + 20}" y="${y + 6}" width="12" height="40" rx="3" fill="${IN}"/>`,
      );
      body.push(text(CARD_WIDTH / 2 + 48, y + 38, move.in, { size: 30, weight: 600, fill: CHIP }));
      y += LINE;
    });
    if (data.hitPoints > 0) {
      body.push(
        text(PAD, y + 34, copy.hit(copy.formatPoints(data.hitPoints)), {
          size: 28,
          weight: 600,
          fill: BOARD_MUTED,
          tabular: true,
        }),
      );
      y += LINE;
    }
    if (data.chip !== null) {
      body.push(
        text(PAD, y + 34, copy.chip(copy.chipNames[data.chip] ?? data.chip), {
          size: 28,
          weight: 600,
          fill: BOARD_MUTED,
        }),
      );
      y += LINE;
    }
  }
  if (fields.has("points") && data.expectedPoints !== null) {
    body.push(text(PAD, y + 40, copy.expectedPoints, { size: 28, weight: 700, fill: BOARD_MUTED }));
    body.push(
      text(CARD_WIDTH - PAD, y + 44, copy.formatPoints(data.expectedPoints), {
        size: 48,
        weight: 800,
        fill: ACCENT,
        anchor: "end",
        tabular: true,
      }),
    );
    y += LINE + 16;
  }
  const height = Math.max(y + PAD, headerBottom + PAD);
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="${CARD_WIDTH}" height="${height}" viewBox="0 0 ${CARD_WIDTH} ${height}">` +
    `<rect width="${CARD_WIDTH}" height="${height}" fill="${BOARD}"/>` +
    `<rect x="0" y="${headerBottom}" width="${CARD_WIDTH}" height="4" fill="${ACCENT}"/>` +
    parts.join("") +
    body.join("") +
    `</svg>`;
  return { svg, width: CARD_WIDTH, height };
}
