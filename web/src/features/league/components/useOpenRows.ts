import { useState } from "react";

/** Which rows of a table stand open on a phone, each row by its own number. */
export function useOpenRows() {
  const [opened, setOpened] = useState<ReadonlySet<number>>(() => new Set());
  const toggle = (row: number) =>
    setOpened((current) => {
      const next = new Set(current);
      if (!next.delete(row)) next.add(row);
      return next;
    });
  return { isOpen: (row: number) => opened.has(row), toggle };
}
