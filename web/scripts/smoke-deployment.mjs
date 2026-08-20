const baseUrl = process.argv[2];

if (!baseUrl) {
  throw new Error("Usage: npm run smoke:deployment -- https://deployment.example");
}

const checks = [
  { path: "/", kind: "html" },
  { path: "/moves", kind: "html" },
  { path: "/rivals", kind: "html" },
  { path: "/league", kind: "html" },
  { path: "/data/index.json", kind: "json", revalidates: true },
];

const delay = (milliseconds) =>
  new Promise((resolvePromise) => setTimeout(resolvePromise, milliseconds));

async function checkEndpoint(check) {
  const url = new URL(check.path, baseUrl);
  let lastError;

  for (let attempt = 1; attempt <= 4; attempt += 1) {
    try {
      const response = await fetch(url, {
        headers: { "cache-control": "no-cache" },
        signal: AbortSignal.timeout(10_000),
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      if (check.kind === "json") {
        await response.json();
      } else {
        const body = await response.text();
        if (!body.toLowerCase().includes("<!doctype html")) {
          throw new Error("response is not the SPA document");
        }
      }

      if (check.revalidates) {
        const cacheControl = response.headers.get("cache-control") ?? "";
        if (!cacheControl.includes("max-age=0") || !cacheControl.includes("must-revalidate")) {
          throw new Error(`unexpected Cache-Control: ${cacheControl || "<missing>"}`);
        }
      }

      console.log(`OK ${response.status} ${url}`);
      return;
    } catch (error) {
      lastError = error;
      if (attempt < 4) await delay(attempt * 1_000);
    }
  }

  throw new Error(`Deployment smoke failed for ${url}`, { cause: lastError });
}

await Promise.all(checks.map(checkEndpoint));
