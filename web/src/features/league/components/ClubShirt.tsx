import type { CSSProperties } from "react";

import { useLanguage } from "../../../i18n/context";
import { clubColours } from "../../../lib/clubs";
import styles from "./ClubShirt.module.css";
import { clubPlate } from "./pitchLook";

/*
 * Our own flat shirt on a 32 by 28 grid, symmetric about x = 16: a scooped neck, short
 * sleeves and a straight hem. It follows no club's kit; the sleeves and the collar are the
 * trim, the rest is the body.
 */
const BODY = "M12 1.5L6.5 3 1 9l3.5 3.5L8 10v16.5h16V10l3.5 2.5L31 9l-5.5-6L20 1.5Q16 5.5 12 1.5z";
const TRIM =
  "M8.5 2.45L6.5 3 1 9l3.5 3.5L8 10zM23.5 2.45L25.5 3 31 9l-3.5 3.5L24 10zM12 1.5Q16 5.5 20 1.5l1.6.44Q16 9 10.4 1.94z";

/**
 * The letters a shirt carries: the first letter of the first and of the last word of the
 * full name, or the one letter of a single name. FPL publishes no squad numbers, so the
 * initials stand where a number would. A letter keeps its accents (Ç, Ö, Ø) and a lower-case
 * one is raised by the page language's rules, so a Turkish page writes 'i' as 'İ' as its
 * own capitals do. Marks and punctuation before a letter (N'Golo, 'Rodri') are passed over.
 */
function initials(name: string, locale: string): string {
  const letters = name
    .normalize("NFC")
    .split(/\s+/)
    .map((word) => word.match(/\p{L}\p{M}*/u)?.[0])
    .filter((letter): letter is string => letter !== undefined);
  const chosen = letters.length > 1 ? [letters[0]!, letters.at(-1)!] : letters;
  return chosen.map((letter) => letter.toLocaleUpperCase(locale)).join("");
}

/**
 * A player's shirt, drawn in their club's colours: the body in the colour the
 * club's plate is filled with, which is its first colour wherever ink or white reads on it
 * at 4.5:1 (clubPlate in pitchLook.ts, the same rule the club-coloured plates follow), and
 * the sleeves and collar in the club's other colour. Every goalkeeper wears one shared
 * colour no club wears (--color-keeper), so the keepers read at a glance, and a club with
 * no colours wears a blank white shirt. The large shirt carries the player's initials in the
 * one text colour chosen for its body; the small one, at 14 px, has no room for 12 px type
 * and carries none.
 *
 * It is decoration: the plate beside it already names the player and the club, so assistive
 * technology skips it rather than hear them twice.
 */
export function ClubShirt({
  code,
  name,
  keeper = false,
  size,
  className,
}: {
  code: string | null | undefined;
  /** The player's full name, read for the initials on a large shirt. */
  name: string;
  keeper?: boolean;
  size: "small" | "large";
  className?: string;
}) {
  const { locale } = useLanguage();
  const colours = keeper ? null : clubColours(code);
  const plate = colours ? clubPlate(code) : null;
  const kind = keeper ? "keeper" : colours && plate ? "club" : "blank";
  const style =
    colours && plate
      ? ({
          "--shirt-body": plate.fill,
          "--shirt-trim": plate.colour === "primary" ? colours.secondary : colours.primary,
          "--shirt-ink": plate.text,
        } as CSSProperties)
      : undefined;
  const letters = size === "large" ? initials(name, locale) : "";
  return (
    <svg
      className={[styles.shirt, styles[size], className].filter(Boolean).join(" ")}
      viewBox="0 0 32 28"
      aria-hidden="true"
      focusable="false"
      data-shirt={kind}
      style={style}
    >
      <path className={styles.body} d={BODY} />
      <path className={styles.trim} d={TRIM} />
      <path className={styles.outline} d={BODY} />
      {letters ? (
        <text className={styles.initials} x="16" y="22">
          {letters}
        </text>
      ) : null}
    </svg>
  );
}
