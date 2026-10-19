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
  id: number;
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
  captain: CardPlayer | null;
  viceCaptain: CardPlayer | null;
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
  id: value.player_id,
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
    captain: player(view.captain),
    viceCaptain: view.vice_captain ? player(view.vice_captain) : null,
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

/**
 * The card's colours. An SVG drawn through an image cannot read the page's custom
 * properties, so the card carries a copy of each token it uses, and the card's test holds
 * every copy equal to its value in tokens.css.
 */
export const CARD_COLOURS = {
  "--color-board": "#10261a",
  "--color-board-muted": "#cfe3d3",
  "--color-pitch": "#3f8f58",
  "--color-pitch-2": "#48995f",
  "--color-chip": "#ffffff",
  "--color-chip-text": "#10261a",
  "--color-lime": "#c6ff3d",
  "--color-out-panel": "#c62828",
  "--color-in-panel": "#1e7b45",
} as const;

const BOARD = CARD_COLOURS["--color-board"];
const BOARD_MUTED = CARD_COLOURS["--color-board-muted"];
const PITCH = CARD_COLOURS["--color-pitch"];
const PITCH_STRIPE = CARD_COLOURS["--color-pitch-2"];
const CHIP = CARD_COLOURS["--color-chip"];
const CHIP_TEXT = CARD_COLOURS["--color-chip-text"];
const ACCENT = CARD_COLOURS["--color-lime"];
const OUT = CARD_COLOURS["--color-out-panel"];
const IN = CARD_COLOURS["--color-in-panel"];
const FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif";

export const CARD_WIDTH = 1080;
const PAD = 56;
const ROW = 104;
const LINE = 62;

// A name plate fills its slot on the row less a gap, so neighbours never touch; the name
// on it shrinks to fit, the same size across the row, and is cut short only at the floor.
const PLATE_HEIGHT = 56;
const PLATE_MAX = 220;
const PLATE_GAP = 12;
const PLATE_PAD = 8;
const NAME_SIZE = 28;
const NAME_FLOOR = 20;
// The captain's and vice's disc sits on the plate's top right corner, inside its width.
const BADGE = 20;

/*
 * An SVG drawn through an image cannot use the page's fonts or measure its own text, so a
 * line's width is estimated from its letters. The advances are fractions of the font size
 * taken on the wide side of the faces system-ui resolves to (Segoe UI, San Francisco,
 * Roboto, Arial) at 700, wider still for capitals and wide letters, so a line that fits by
 * the estimate fits on the device.
 */
const ADVANCES: readonly (readonly [string, number])[] = [
  [" ijlı.,:;'!|", 0.3],
  ["ftI", 0.4],
  ["r-()·", 0.44],
  ["J", 0.56],
  ["w", 0.84],
  ["m", 0.94],
  ["MW", 1.04],
  ["…→&", 1],
];
const ADVANCE = new Map(
  ADVANCES.flatMap(([letters, em]) => Array.from(letters, (letter) => [letter, em] as const)),
);

function advance(letter: string): number {
  // A Turkish or accented letter takes its base letter's width: ş as s, İ as I.
  const base = letter.normalize("NFD").charAt(0) || letter;
  const known = ADVANCE.get(letter) ?? ADVANCE.get(base);
  if (known !== undefined) return known;
  if (/[a-z]/.test(base)) return 0.58;
  if (/[A-Z]/.test(base)) return 0.78;
  if (/[0-9]/.test(base)) return 0.6;
  return (base.codePointAt(0) ?? 0) >= 0x2e80 ? 1.05 : 0.8;
}

/** The width a line takes on the card, by the estimate above. */
export function textWidth(value: string, size: number, weight = 600): number {
  const em = Array.from(value).reduce((sum, letter) => sum + advance(letter), 0);
  return em * size * (weight >= 800 ? 1.05 : 1);
}

/**
 * The line at the largest size from `size` down to `floor` that fits `room`; a line still
 * too wide at the floor is cut and ends in an ellipsis.
 */
export function fitText(
  value: string,
  room: number,
  size: number,
  floor = size,
  weight = 600,
): { value: string; size: number } {
  const em = textWidth(value, 1, weight);
  if (em * size <= room) return { value, size };
  const shrunk = Math.floor(room / em);
  if (shrunk >= floor) return { value, size: shrunk };
  const letters = Array.from(value);
  for (let end = letters.length - 1; end > 0; end -= 1) {
    const cut = `${letters
      .slice(0, end)
      .join("")
      .replace(/[\s·.,:-]+$/u, "")}…`;
    if (textWidth(cut, floor, weight) <= room) return { value: cut, size: floor };
  }
  return { value: "…", size: floor };
}

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
  {
    size = 32,
    weight = 600,
    fill = CHIP_TEXT as string,
    anchor = "start",
    tabular = false,
    room = Infinity,
    floor = Math.round(size * 0.75),
  } = {},
): string {
  const line = fitText(value, room, size, floor, weight);
  const numbers = tabular ? ' font-variant-numeric="tabular-nums"' : "";
  return `<text x="${x}" y="${y}" font-family="${FONT}" font-size="${line.size}" font-weight="${weight}" fill="${fill}" text-anchor="${anchor}"${numbers}>${escape(line.value)}</text>`;
}

const plateWidth = (slot: number) => Math.min(PLATE_MAX, slot - PLATE_GAP);

function plate(
  cx: number,
  y: number,
  width: number,
  name: { value: string; size: number },
  mark: string | null,
): string {
  const x = cx - width / 2;
  const badge =
    mark === null
      ? ""
      : `<circle cx="${x + width - BADGE}" cy="${y - 8}" r="${BADGE}" fill="${ACCENT}"/>${text(x + width - BADGE, y, mark, { size: 24, weight: 800, anchor: "middle" })}`;
  const baseline = y + PLATE_HEIGHT / 2 + Math.round(name.size * 0.35);
  return `<g class="plate"><rect x="${x}" y="${y}" width="${width}" height="${PLATE_HEIGHT}" rx="12" fill="${CHIP}"/>${text(cx, baseline, name.value, { size: name.size, anchor: "middle" })}${badge}</g>`;
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
  parts.push(
    text(PAD, y + 44, copy.title(data.gameweek), {
      size: 48,
      weight: 800,
      fill: ACCENT,
      room: CARD_WIDTH - 2 * PAD,
    }),
  );
  y += 72;
  if (fields.has("team") && data.teamName) {
    parts.push(
      text(PAD, y + 34, data.teamName, {
        size: 36,
        weight: 700,
        fill: CHIP,
        room: CARD_WIDTH - 2 * PAD,
      }),
    );
    y += 46;
  }
  if (fields.has("team") && data.managerName) {
    parts.push(
      text(PAD, y + 34, data.managerName, {
        size: 28,
        weight: 500,
        fill: BOARD_MUTED,
        room: CARD_WIDTH - 2 * PAD,
      }),
    );
    y += 46;
  }
  const headerBottom = y + 16;

  const body: string[] = [];
  y = headerBottom + 32;
  if (fields.has("lineup")) {
    const pitchTop = y - 16;
    // Room above the first row for a captain's disc, which rises above its plate.
    y += 20;
    const rows = ORDER.map((position) => data.starters.filter((p) => p.position === position));
    rows.forEach((row) => {
      const slot = CARD_WIDTH / (row.length + 1);
      const width = plateWidth(slot);
      const room = width - 2 * PLATE_PAD;
      const size = Math.min(
        NAME_SIZE,
        ...row.map((p) => fitText(p.name, room, NAME_SIZE, NAME_FLOOR).size),
      );
      row.forEach((p, index) => {
        const mark = !fields.has("captain")
          ? null
          : p.id === data.captain?.id
            ? "C"
            : p.id === data.viceCaptain?.id
              ? "V"
              : null;
        body.push(plate(slot * (index + 1), y, width, fitText(p.name, room, size), mark));
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
    const benchAt = PAD + Math.ceil(textWidth(copy.bench, 26, 700)) + 20;
    body.push(text(PAD, y + 34, copy.bench, { size: 26, weight: 700, fill: BOARD_MUTED }));
    body.push(
      text(benchAt, y + 34, data.bench.map((p) => p.name).join(" · "), {
        size: 28,
        weight: 500,
        fill: CHIP,
        room: CARD_WIDTH - PAD - benchAt,
      }),
    );
    y += LINE + 8;
  }
  if (fields.has("captain") && data.captain !== null) {
    const line = data.viceCaptain
      ? `${copy.captain}: ${data.captain.name} · ${copy.viceCaptain}: ${data.viceCaptain.name}`
      : `${copy.captain}: ${data.captain.name}`;
    body.push(
      text(PAD, y + 34, line, { size: 32, weight: 700, fill: CHIP, room: CARD_WIDTH - 2 * PAD }),
    );
    y += LINE;
  }
  if (fields.has("transfers")) {
    body.push(text(PAD, y + 34, copy.transfers, { size: 26, weight: 700, fill: BOARD_MUTED }));
    y += 52;
    if (data.moves.length === 0) {
      body.push(text(PAD, y + 34, copy.noTransfers, { size: 30, weight: 600, fill: CHIP }));
      y += LINE;
    }
    const arrow = CARD_WIDTH / 2 - 10;
    data.moves.forEach((move) => {
      body.push(`<rect x="${PAD}" y="${y + 6}" width="12" height="40" rx="3" fill="${OUT}"/>`);
      body.push(
        text(PAD + 28, y + 38, move.out, {
          size: 30,
          weight: 600,
          fill: CHIP,
          room: arrow - 28 - (PAD + 28),
        }),
      );
      body.push(text(arrow, y + 38, "→", { size: 30, fill: BOARD_MUTED, anchor: "middle" }));
      body.push(
        `<rect x="${CARD_WIDTH / 2 + 20}" y="${y + 6}" width="12" height="40" rx="3" fill="${IN}"/>`,
      );
      body.push(
        text(CARD_WIDTH / 2 + 48, y + 38, move.in, {
          size: 30,
          weight: 600,
          fill: CHIP,
          room: CARD_WIDTH - PAD - (CARD_WIDTH / 2 + 48),
        }),
      );
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
