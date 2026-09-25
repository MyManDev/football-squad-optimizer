/*
 * The member page's few icons, inline as in the approved artboards. Every one is hidden
 * from assistive technology: the words beside it (ÇIKAN, GİREN, the stamp, the disclosure)
 * carry the meaning, so colour and shape are never the only signal.
 */

const STROKE = {
  fill: "none",
  stroke: "currentColor",
  strokeLinecap: "round",
  strokeLinejoin: "round",
} as const;

/** The board's arrow: down for the player going out, up for the one coming in. */
export function BoardArrow({ direction }: { direction: "up" | "down" }) {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 14 14"
      aria-hidden="true"
      focusable="false"
      strokeWidth={2}
      {...STROKE}
    >
      {direction === "down" ? (
        <path d="M7 1.5v11M2.5 8l4.5 4.5L11.5 8" />
      ) : (
        <path d="M7 12.5v-11M2.5 6L7 1.5 11.5 6" />
      )}
    </svg>
  );
}

export function CheckIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 16 16"
      aria-hidden="true"
      focusable="false"
      strokeWidth={2.2}
      {...STROKE}
    >
      <path d="M2.5 8.5l3.5 3.5 7.5-8" />
    </svg>
  );
}

export function InfoIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 16 16"
      aria-hidden="true"
      focusable="false"
      strokeWidth={1.5}
      {...STROKE}
    >
      <circle cx="8" cy="8" r="6.25" />
      <path d="M8 7.25v4" />
      <circle cx="8" cy="4.9" r="0.4" fill="currentColor" />
    </svg>
  );
}

/** Up and down chevrons: the WHO block's 'change member'. */
export function SwitchIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 14 14"
      aria-hidden="true"
      focusable="false"
      strokeWidth={1.6}
      {...STROKE}
    >
      <path d="M4 5.5L7 2.5l3 3M4 8.5l3 3 3-3" />
    </svg>
  );
}

/** A disclosure's chevron, turned by the stylesheet when the section opens. */
export function DisclosureIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="14"
      height="14"
      viewBox="0 0 14 14"
      aria-hidden="true"
      focusable="false"
      strokeWidth={1.6}
      {...STROKE}
    >
      <path d="M5 2.5L9.5 7 5 11.5" />
    </svg>
  );
}
