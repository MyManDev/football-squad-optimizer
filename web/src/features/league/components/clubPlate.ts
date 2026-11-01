import { AA, contrastRatio } from "../../../design/contrastRatio";
import { CLUB_COLOURS } from "../../../lib/clubs";

/** The ink and white a plate can print in; the colour-token test holds INK to tokens.css. */
export const PLATE_INK = "#10261a";
export const PLATE_WHITE = "#ffffff";

export interface ClubPlate {
  /** Which of the club's two colours the plate is filled with. */
  colour: "primary" | "secondary";
  fill: string;
  text: string;
}

/**
 * The colours a club's plate takes: its primary with ink or white, whichever reads better,
 * if that reaches 4.5:1; otherwise its secondary the same way. Every figure, name and code
 * on the plate is printed in that one text colour. A club with no colours, or with neither
 * colour readable, keeps the white plate (null).
 */
export function clubPlate(code: string | null | undefined): ClubPlate | null {
  const colours = code ? CLUB_COLOURS[code.toUpperCase()] : undefined;
  if (!colours) return null;
  for (const colour of ["primary", "secondary"] as const) {
    const fill = colours[colour];
    const text =
      contrastRatio(PLATE_INK, fill) >= contrastRatio(PLATE_WHITE, fill) ? PLATE_INK : PLATE_WHITE;
    if (contrastRatio(text, fill) >= AA) return { colour, fill, text };
  }
  return null;
}
