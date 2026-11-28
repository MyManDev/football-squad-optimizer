/** The Node clock remains outside a synchronously blocked browser main thread. */
export async function guardedBrowserSolve(run, closeOwnContext, milliseconds = 315_000) {
  const started = performance.now();
  let timer;
  try {
    const result = await Promise.race([
      Promise.resolve()
        .then(run)
        .catch((error) => ({
          reply: { kind: "failed", status: String(error) },
          elapsed_seconds: null,
        })),
      new Promise((resolve) => {
        timer = setTimeout(
          () =>
            resolve({
              reply: { kind: "timeout", status: "external Node watchdog" },
              elapsed_seconds: null,
            }),
          milliseconds,
        );
      }),
    ]);
    const outside = (performance.now() - started) / 1000;
    if (result.reply.kind === "timeout") await closeOwnContext();
    return {
      ...result,
      outer_elapsed_seconds: outside,
      ...(result.reply.kind === "timeout" ? { censored_at_seconds: outside } : {}),
    };
  } finally {
    clearTimeout(timer);
  }
}
