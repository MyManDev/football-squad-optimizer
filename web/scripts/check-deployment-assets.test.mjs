import { afterEach, describe, expect, it } from "vitest";
import { mkdtemp, mkdir, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { inspectDeploymentArtifact } from "./check-deployment-assets.mjs";

const temporaryDirectories = [];

const POLICY =
  "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; connect-src 'self' https://api.example; object-src 'none'; base-uri 'none'; frame-ancestors 'none'";

function headers(policy = POLICY) {
  return `/*\n  Content-Security-Policy: ${policy}\n\n/data/*\n  Cache-Control: public, max-age=0, must-revalidate\n`;
}

async function validArtifact() {
  const root = await mkdtemp(join(tmpdir(), "squadopt-deployment-"));
  temporaryDirectories.push(root);
  await mkdir(join(root, "data"));
  await writeFile(join(root, "index.html"), "<!doctype html><title>SquadOpt</title>");
  await writeFile(join(root, "data", "index.json"), '{"version":1}');
  await writeFile(join(root, "data", "404.html"), "<!doctype html><title>404</title>");
  await mkdir(join(root, "assets"), { recursive: true });
  await writeFile(join(root, "assets", "404.html"), "<!doctype html><title>404</title>");
  await writeFile(join(root, "_headers"), headers());
  return root;
}

afterEach(async () => {
  await Promise.all(
    temporaryDirectories
      .splice(0)
      .map((directory) => rm(directory, { force: true, recursive: true })),
  );
});

describe("deployment artifact preflight", () => {
  it("accepts a static site with the required data cache rule", async () => {
    const root = await validArtifact();
    await expect(inspectDeploymentArtifact(root)).resolves.toMatchObject({ fileCount: 5 });
  });

  it("requires the not-found document that keeps /data/ off the shell", async () => {
    const root = await validArtifact();
    await rm(join(root, "data", "404.html"));
    await expect(inspectDeploymentArtifact(root)).rejects.toThrow("missing data/404.html");
  });

  it("requires assets/404.html, so a missing asset is not the cached shell", async () => {
    const root = await validArtifact();
    await rm(join(root, "assets", "404.html"));
    await expect(inspectDeploymentArtifact(root)).rejects.toThrow("missing assets/404.html");
  });

  it("requires the cache policy on /data/* itself", async () => {
    const root = await validArtifact();
    await writeFile(
      join(root, "_headers"),
      "/data/*\n  X-Content-Type-Options: nosniff\n\n/assets/*\n  Cache-Control: public, max-age=0, must-revalidate\n",
    );
    await expect(inspectDeploymentArtifact(root)).rejects.toThrow("/data/* cache rule");
  });

  it("requires the site-wide Content-Security-Policy", async () => {
    const root = await validArtifact();
    await writeFile(
      join(root, "_headers"),
      "/data/*\n  Cache-Control: public, max-age=0, must-revalidate\n",
    );
    await expect(inspectDeploymentArtifact(root)).rejects.toThrow("exactly one Content-Security");
  });

  it.each([
    [POLICY.replace("https://api.example", "{advice-api-origin}"), "unfilled word"],
    [POLICY.replace(" 'wasm-unsafe-eval'", ""), "script-src lacks 'wasm-unsafe-eval'"],
    [POLICY.replace("object-src 'none'", "object-src 'self'"), "object-src lacks 'none'"],
    [
      POLICY.replace("script-src 'self'", "script-src 'self' 'unsafe-inline'"),
      "allows 'unsafe-inline'",
    ],
    [
      POLICY.replace("script-src 'self'", "script-src 'self' https://cdn.example.net"),
      "allows https://cdn.example.net",
    ],
    [POLICY.replace("https://api.example", "https:"), "connect-src allows any host"],
  ])("refuses the policy %s", async (policy, message) => {
    const root = await validArtifact();
    await writeFile(join(root, "_headers"), headers(policy));
    await expect(inspectDeploymentArtifact(root)).rejects.toThrow(message);
  });

  it.each(["404.html", "_worker.js"])("rejects a top-level %s", async (name) => {
    const root = await validArtifact();
    await writeFile(join(root, name), "forbidden");
    await expect(inspectDeploymentArtifact(root)).rejects.toThrow("forbidden Pages content");
  });

  it("rejects a top-level Pages Functions directory", async () => {
    const root = await validArtifact();
    await mkdir(join(root, "functions"));
    await expect(inspectDeploymentArtifact(root)).rejects.toThrow("forbidden Pages content");
  });

  const symlinkTest = process.platform === "win32" ? it.skip : it;
  symlinkTest("rejects symbolic links without following them", async () => {
    const root = await validArtifact();
    await symlink("index.html", join(root, "linked.html"));
    await expect(inspectDeploymentArtifact(root)).rejects.toThrow("symbolic link");
  });

  it("enforces the file count and per-file size limits", async () => {
    const root = await validArtifact();
    await expect(inspectDeploymentArtifact(root, { maxFiles: 2 })).rejects.toThrow("file limit");
    await expect(inspectDeploymentArtifact(root, { maxFileBytes: 4 })).rejects.toThrow(
      "byte limit",
    );
  });

  it("rejects malformed published JSON", async () => {
    const root = await validArtifact();
    await writeFile(join(root, "data", "index.json"), "not-json");
    await expect(inspectDeploymentArtifact(root)).rejects.toThrow("not valid JSON");
  });
});
