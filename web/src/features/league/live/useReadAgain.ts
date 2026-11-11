/**
 * A read made again while what it holds is behind (refused, or naming another week than the
 * live one): one minute after, then two, four and eight minutes, then no more, so a document
 * that keeps failing costs four reads, not one a minute all match long. `reset` (Yenile) starts
 * the count again, and so does another `key` (another rival, another member).
 */

import { useCallback, useEffect, useState } from "react";

/** The waits before each read made again. */
export const READ_AGAIN_MS = [60_000, 120_000, 240_000, 480_000] as const;

export function useReadAgain(
  behind: boolean,
  read: () => unknown,
  reading: boolean,
  key: unknown,
): () => void {
  const [tries, setTries] = useState({ key, count: 0 });
  if (tries.key !== key) setTries({ key, count: 0 });
  const count = tries.key === key ? tries.count : 0;
  useEffect(() => {
    if (!behind || reading || count >= READ_AGAIN_MS.length) return undefined;
    const timer = setTimeout(() => {
      setTries((current) => ({ ...current, count: current.count + 1 }));
      void read();
    }, READ_AGAIN_MS[count]);
    return () => clearTimeout(timer);
  }, [behind, reading, count, read]);
  return useCallback(() => setTries((current) => ({ ...current, count: 0 })), []);
}
