import type { ReactNode } from "react";

import type { NavKey } from "./nav";

/*
 * The shell's icons, drawn inline as in the approved artboards: 18 px strokes in the
 * current text colour, hidden from assistive technology because every control that shows
 * one also carries its words. No icon library.
 */

const STROKE = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round",
  strokeLinejoin: "round",
} as const;

const NAV_PATHS: Record<NavKey, ReactNode> = {
  thisWeek: <path d="M5.5 2.5v12M2.5 11.5l3 3 3-3M12.5 15.5v-12M9.5 6.5l3-3 3 3" />,
  squad: (
    <path d="M6.5 2.5L2.5 4.5 4 8l2-.8v8.3h6V7.2l2 .8 1.5-3.5-4-2c-.4 1.2-1.4 2-2.5 2s-2.1-.8-2.5-2z" />
  ),
  league: <path d="M2 15.5h14M3 15.5v-5h4v5M7 15.5v-9h4v9M11 15.5V12h4v3.5" />,
  fixtures: (
    <>
      <rect x="2.5" y="3.5" width="13" height="12" rx="1.5" />
      <path d="M2.5 7.5h13M6 2v3M12 2v3" />
    </>
  ),
  contribute: (
    <>
      <path d="M3 15l.8-3.6 7.8-7.8a1.4 1.4 0 0 1 2 0l.8.8a1.4 1.4 0 0 1 0 2l-7.8 7.8z" />
      <path d="M10.2 5l2.8 2.8" />
    </>
  ),
};

export function NavIcon({ name, className }: { name: NavKey; className?: string }) {
  return (
    <svg
      className={className}
      width="18"
      height="18"
      viewBox="0 0 18 18"
      aria-hidden="true"
      focusable="false"
      {...STROKE}
    >
      {NAV_PATHS[name]}
    </svg>
  );
}

/** Two stacked bars, red over green, like the fourth official's board. */
export function BrandMark({ className, small }: { className?: string; small?: boolean }) {
  return small ? (
    <svg className={className} width="14" height="18" viewBox="0 0 14 18" aria-hidden="true">
      <rect x="0" y="0" width="14" height="8" rx="1.5" data-bar="out" />
      <rect x="0" y="10" width="14" height="8" rx="1.5" data-bar="in" />
    </svg>
  ) : (
    <svg className={className} width="16" height="20" viewBox="0 0 16 20" aria-hidden="true">
      <rect x="0" y="0" width="16" height="9" rx="2" data-bar="out" />
      <rect x="0" y="11" width="16" height="9" rx="2" data-bar="in" />
    </svg>
  );
}

export function ChevronIcon({ direction }: { direction: "left" | "right" }) {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 18 18"
      aria-hidden="true"
      focusable="false"
      {...STROKE}
    >
      <path
        strokeWidth={1.8}
        d={direction === "left" ? "M11 4.5L6.5 9l4.5 4.5" : "M7 4.5L11.5 9 7 13.5"}
      />
    </svg>
  );
}

export function MenuIcon() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 20 20"
      aria-hidden="true"
      focusable="false"
      {...STROKE}
    >
      <path strokeWidth={1.8} d="M3 5.5h14M3 10h14M3 14.5h14" />
    </svg>
  );
}

export function CloseIcon() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 20 20"
      aria-hidden="true"
      focusable="false"
      {...STROKE}
    >
      <path strokeWidth={1.8} d="M5 5l10 10M15 5L5 15" />
    </svg>
  );
}

/** Two sliders: the plan's settings. */
export function PlanIcon() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 18 18"
      aria-hidden="true"
      focusable="false"
      {...STROKE}
    >
      <path d="M2.5 5h7M13.5 5h2M2.5 13h2M8.5 13h7" />
      <circle cx="11.5" cy="5" r="2" />
      <circle cx="6.5" cy="13" r="2" />
    </svg>
  );
}

/** A pulse line: the service's operating state. */
export function StatusIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="18"
      height="18"
      viewBox="0 0 18 18"
      aria-hidden="true"
      focusable="false"
      {...STROKE}
    >
      <path d="M1.5 9.5h3.5l2-5 4 9 2-4h3.5" />
    </svg>
  );
}

export function CalendarIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 16 16"
      aria-hidden="true"
      focusable="false"
      {...STROKE}
    >
      <path strokeWidth={1.5} d="M2 6.5h12M5.5 1.5v3M10.5 1.5v3" />
      <rect strokeWidth={1.5} x="2" y="3" width="12" height="11" rx="1.5" />
    </svg>
  );
}
