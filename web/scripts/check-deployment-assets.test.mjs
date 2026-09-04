import { afterEach, describe, expect, it } from "vitest";
import { mkdtemp, mkdir, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { inspectDeploymentArtifact } from "./check-deployment-assets.mjs";

const temporaryDirectories = [];

async function validArtifact() {
  const root = await mkdtemp(join(tmpdir(), "squadopt-deployment-"));
  temporaryDirectories.push(root);
  await mkdir(join(root, "data"));
  await writeFile(join(root, "index.html"), "<!doctype html><title>SquadOpt</title>");
  await writeFile(join(root, "data", "index.json"), '{"version":1}');
  await writeFile(
    join(root, "_headers"),
    "/data/*\n  Cache-Control: public, max-age=0, must-revalidate\n",
  );
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
    await expect(inspectDeploymentArtifact(root)).resolves.toMatchObject({ fileCount: 3 });
  });

  it("requires the cache policy on /data/* itself", async () => {
    const root = await validArtifact();
    await writeFile(
      join(root, "_headers"),
      "/data/*\n  X-Content-Type-Options: nosniff\n\n/assets/*\n  Cache-Control: public, max-age=0, must-revalidate\n",
    );
    await expect(inspectDeploymentArtifact(root)).rejects.toThrow("/data/* cache rule");
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
