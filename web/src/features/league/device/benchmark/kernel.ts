/** Data-free calibration only, run after the same worker has loaded its solver. */
export function kernel(count: number): number {
  let value = 17;
  for (let i = 0; i < count; i += 1) value = Math.imul(value ^ (value >>> 13), 1597334677) | 0;
  return value;
}

export function probe(count: number): { milliseconds: number; checksum: number } {
  const started = performance.now();
  const checksum = kernel(count);
  return { milliseconds: performance.now() - started, checksum };
}
