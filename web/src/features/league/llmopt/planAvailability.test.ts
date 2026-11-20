import { createHash, webcrypto } from "node:crypto";
import { afterEach, expect, it, vi } from "vitest";
import cases from "../../../fixtures/device-plan/instances.json";
import { mockEntrySquadEnvelopes } from "../../../fixtures/league";
import { HttpAdviceClient } from "../advice/adviceClient";
import { deviceAdviceClient } from "../device/adviceClient";
import type { DevicePlanDocument, DevicePlanEntry } from "../device/types";
import { readPlanAvailability } from "./planAvailability";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function transport() {
  vi.stubGlobal("crypto", webcrypto);
  const hashes = vi.spyOn(webcrypto.subtle, "digest");
  const document = cases.document as unknown as DevicePlanDocument;
  const entry = cases.members[0]!.entry as unknown as DevicePlanEntry;
  const squad = {
    ...mockEntrySquadEnvelopes[35249001]!.payload,
    source_snapshot_id: document.source_snapshot_id,
    season: document.season,
    gameweek: document.gameweek,
    device_plan: entry,
  };
  const capabilities = {
    contract_version: "league_capabilities_v1",
    league_id: squad.league_id,
    capture_snapshot_id: squad.source_snapshot_id,
    season: squad.season,
    gameweek: squad.gameweek,
    strategies: { "saf-puan": { windows: [1], requires_rival: false } },
    top100: { available: false, weights: [0] },
    managers_word: { available: false },
    llmopt_vnext: true,
    plan_data_id: "b".repeat(64),
  };
  const get = vi.fn(async () => Response.json(capabilities));
  const envelope = {
    contract_version: "provisional_league_ui_v1" as const,
    generated_at_utc: "2026-11-19T00:00:00Z",
    source_kind: "example" as const,
    payload: document,
  };
  const load = vi.fn(async () => envelope);
  const client = deviceAdviceClient(
    new HttpAdviceClient("https://advice.example", get),
    squad,
    load,
  );
  const check = (kind: "device" | "server") =>
    readPlanAvailability(
      kind,
      () => client.readCapabilities!(squad.league_id),
      client.readDeviceDataId,
    );
  return { capabilities, check, get, load, hashes, envelope, entry };
}

it("reads and hashes device inputs once for all checks in one action and rechecks on the next", async () => {
  const { check, get, load, hashes, envelope, entry } = transport();
  const current = createHash("sha256")
    .update(JSON.stringify({ document: envelope.payload, entry }))
    .digest("hex");
  const message = await check("device");
  expect(message.matches("device", current)).toBe(true);
  expect(message.matches("device", current)).toBe(true);
  expect(message.matches("server", current)).toBe(false);
  expect(message.matches("device", "c".repeat(64))).toBe(false);
  expect(get).toHaveBeenCalledTimes(1);
  expect(load).toHaveBeenCalledTimes(1);
  expect(hashes).toHaveBeenCalledTimes(1);

  load.mockResolvedValue({
    ...envelope,
    payload: { ...envelope.payload, players: [...envelope.payload.players].reverse() },
  });
  const selection = await check("device");
  expect(selection.matches("device", current)).toBe(false);
  expect(get).toHaveBeenCalledTimes(2);
  expect(load).toHaveBeenCalledTimes(2);
  expect(hashes).toHaveBeenCalledTimes(2);
});

it("checks current server data without fetching device inputs, including after a new release", async () => {
  const { check, get, load, hashes, capabilities } = transport();
  const original = capabilities.plan_data_id;
  const message = await check("server");
  expect(message.matches("server", original)).toBe(true);
  expect(message.matches("device", original)).toBe(false);
  expect(get).toHaveBeenCalledTimes(1);
  capabilities.plan_data_id = "c".repeat(64);
  const selection = await check("server");
  expect(selection.matches("server", original)).toBe(false);
  expect(selection.matches("server", capabilities.plan_data_id)).toBe(true);
  capabilities.llmopt_vnext = false;
  const closed = await check("device");
  expect(closed.grant).toBeUndefined();
  expect(closed.matches("device", original)).toBe(false);
  expect(get).toHaveBeenCalledTimes(3);
  expect(load).not.toHaveBeenCalled();
  expect(hashes).not.toHaveBeenCalled();
});
