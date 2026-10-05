/** Bound both transport and body decoding, and propagate cancellation to fetch. */
export interface RequestOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
}

export const DEFAULT_REQUEST_TIMEOUT_MS = 15_000;

export function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}

/**
 * Read and drop the body of a response the caller will not use. Chromium keeps a response
 * whose body is never read open until it is collected, so a refused 404 left the page
 * holding the request and never network-idle. A refusal's body is small; one that fails to
 * read (the request was aborted) has nothing left open.
 */
export async function discardBody(response: Response): Promise<void> {
  try {
    await response.arrayBuffer();
  } catch {
    // Aborted or failed mid-body: nothing is left open.
  }
}

export async function withRequestDeadline<T>(
  operation: (signal: AbortSignal) => Promise<T>,
  { signal, timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS }: RequestOptions = {},
): Promise<T> {
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    throw new RangeError("Request timeout must be positive and finite.");
  }
  const controller = new AbortController();
  const cancel = () => controller.abort(new DOMException("Request cancelled.", "AbortError"));
  if (signal?.aborted) cancel();
  else signal?.addEventListener("abort", cancel, { once: true });
  const timer = setTimeout(
    () => controller.abort(new DOMException("Request timed out.", "TimeoutError")),
    timeoutMs,
  );
  let rejectAborted: () => void = () => {};
  const aborted = new Promise<never>((_, reject) => {
    rejectAborted = () => reject(controller.signal.reason);
    if (controller.signal.aborted) rejectAborted();
    else controller.signal.addEventListener("abort", rejectAborted, { once: true });
  });
  try {
    // A custom transport can ignore AbortSignal; the caller must still settle.
    return await Promise.race([
      aborted,
      Promise.resolve().then(() => {
        controller.signal.throwIfAborted();
        return operation(controller.signal);
      }),
    ]);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", cancel);
    controller.signal.removeEventListener("abort", rejectAborted);
  }
}

export function cancellableDelay(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const finish = () => {
      clearTimeout(timer);
      signal.removeEventListener("abort", finish);
      resolve();
    };
    const timer = setTimeout(finish, ms);
    if (signal.aborted) finish();
    else signal.addEventListener("abort", finish, { once: true });
  });
}
