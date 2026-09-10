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
