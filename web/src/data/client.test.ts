import { afterEach, expect, it, vi } from "vitest";
import { StaticDataClient } from "./client";

afterEach(() => vi.unstubAllGlobals());

it.each([null, [], "wrong"])(
  "rejects invalid legacy payload %j before rendering",
  async (payload) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              contract_version: "ui_view_v1",
              generated_at_utc: "2026-09-09T00:00:00Z",
              payload,
            }),
          ),
      ),
    );
    await expect(new StaticDataClient().getIndex()).rejects.toThrow(
      "Invalid published view payload",
    );
  },
);

it.each([
  [404, "NotFoundError"],
  [502, "Error"],
])("reads a %i answer's body before refusing it", async (status, name) => {
  const response = new Response("<!doctype html><p>No document is published.</p>", { status });
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response),
  );
  await expect(new StaticDataClient().getStatus("2026-27")).rejects.toMatchObject({ name });
  expect(response.bodyUsed).toBe(true);
});

it("reads a missing live score's body before refusing it", async () => {
  const response = new Response("<!doctype html>", { status: 404 });
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response),
  );
  await expect(new StaticDataClient().getLiveScore("2026-27", 6)).rejects.toMatchObject({
    name: "NotFoundError",
  });
  expect(response.bodyUsed).toBe(true);
});
