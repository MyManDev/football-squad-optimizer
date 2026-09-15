import { expect, it, vi } from "vitest";

import {
  mockEntryAdviceEnvelope,
  mockEntryAdviceIndex,
  mockLeagueMembersEnvelope,
} from "../../../fixtures/league";
import {
  HttpAdviceClient,
  StaticOnlyAdviceClient,
  FallbackAdviceClient,
  type AdviceRequest,
} from "./adviceClient";
import { checkedAdvice } from "./adviceResponse";
import { canComputeAdvice, resolvePublishedAdvice, selectedAdviceRequest } from "./adviceSelection";
import { sameAdviceRequest } from "./useAdviceJob";
import { TOP100_WEIGHTS } from "./top100Weight";

const request: AdviceRequest = { leagueId: 352490, entryId: 101, strategy: "saf-puan", window: 1 };

it.each(TOP100_WEIGHTS)(
  "carries %s through GET and POST and checks the returned setting",
  async (weight) => {
    const envelope = mockEntryAdviceEnvelope(101, "saf-puan", 1);
    envelope.payload.top100_weight_percent = weight;
    envelope.payload.top100_weight_source = "personal";
    const transport = vi.fn(async () => new Response(JSON.stringify(envelope)));
    const client = new HttpAdviceClient("https://api.example", transport);
    const selected = { ...request, top100WeightPercent: weight };
    await expect(client.readAdvice(selected)).resolves.toMatchObject({ kind: "advice" });
    await expect(client.requestAdvice(selected)).resolves.toMatchObject({ kind: "advice" });
    const calls = transport.mock.calls as unknown as [string, RequestInit][];
    expect(new URL(calls[0]![0]).searchParams.get("top100_weight_percent")).toBe(String(weight));
    expect(JSON.parse(String(calls[1]![1].body)).top100_weight_percent).toBe(weight);
    expect(() => checkedAdvice(envelope, request)).toThrow();
    expect(() => checkedAdvice(envelope, { ...selected, top100WeightPercent: 99 })).toThrow();
    delete envelope.payload.top100_weight_source;
    expect(() => checkedAdvice(envelope, selected)).toThrow();
  },
);

it("never serves published advice as a personal weight when the backend fails", async () => {
  const loader = vi.fn(async () => mockEntryAdviceEnvelope(101, "saf-puan", 1));
  const client = new FallbackAdviceClient(
    new HttpAdviceClient("https://api.example", async () => {
      throw new Error("offline");
    }),
    new StaticOnlyAdviceClient(loader),
  );
  for (const weight of TOP100_WEIGHTS) {
    const selected = { ...request, top100WeightPercent: weight };
    await expect(client.readAdvice(selected)).resolves.toEqual({ kind: "not-computed" });
    await expect(client.requestAdvice(selected)).resolves.toEqual({ kind: "unavailable" });
  }
  expect(loader).not.toHaveBeenCalled();
});

it("a changed weight is a new request, including zero and the published setting", () => {
  expect(sameAdviceRequest(request, { ...request, top100WeightPercent: null })).toBe(true);
  for (const weight of TOP100_WEIGHTS) {
    expect(sameAdviceRequest(request, { ...request, top100WeightPercent: weight })).toBe(false);
    for (const other of TOP100_WEIGHTS) {
      expect(
        sameAdviceRequest(
          { ...request, top100WeightPercent: weight },
          { ...request, top100WeightPercent: other },
        ),
      ).toBe(weight === other);
    }
  }
});

it("personal URL choices cannot resolve to a static publication or silently accept a bad weight", () => {
  const members = mockLeagueMembersEnvelope.payload.members;
  const index = mockEntryAdviceIndex(35249001).payload;
  for (const weight of TOP100_WEIGHTS) {
    const selection = resolvePublishedAdvice(
      new URLSearchParams(`top100=${weight}`),
      352490,
      35249001,
      members,
      index,
    );
    expect(selection.request.top100WeightPercent).toBe(weight);
    expect(selection.path).toBeNull();
    expect(canComputeAdvice(selection.request)).toBe(true);
  }
  for (const raw of ["", "15", "-5", "50.0", "abc", "100"]) {
    const invalid = selectedAdviceRequest(
      new URLSearchParams(`top100=${raw}`),
      352490,
      35249001,
      members,
    );
    expect(canComputeAdvice(invalid)).toBe(false);
  }
});
