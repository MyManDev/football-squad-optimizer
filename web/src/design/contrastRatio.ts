/**
 * The WCAG contrast ratio of two six-digit hex colours (#1136). The colour-token test checks
 * every text pairing with it, and the club plates choose their text colour with it, so a
 * plate is drawn only in a pairing the test would pass.
 */

/** WCAG AA for body text: every text pairing on the page reaches it. */
export const AA = 4.5;

function luminance(colour: string): number {
  const channels = [1, 3, 5].map((start) => parseInt(colour.slice(start, start + 2), 16) / 255);
  const [r, g, b] = channels.map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;
}

export function contrastRatio(foreground: string, background: string): number {
  const [light, dark] = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return (light! + 0.05) / (dark! + 0.05);
}
