import { useContext, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { ShellContext, type ShellSlot } from "./ShellContext";

/**
 * Renders its children in one of the sidebar's slots.
 *
 * Without a shell (a page rendered on its own, as the unit tests do) the children render
 * inline, where the component stands, so every control is still on the page exactly once.
 * Inside a shell whose slot has not mounted yet it renders nothing for that moment rather
 * than rendering inline and then moving, which would mount the children twice.
 */
export function ShellPortal({ slot, children }: { slot: ShellSlot; children: ReactNode }) {
  const shell = useContext(ShellContext);
  if (!shell) return <>{children}</>;
  const target = slot === "who" ? shell.whoSlot : shell.planSlot;
  return target ? createPortal(children, target) : null;
}
