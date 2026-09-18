import { expect, it, vi } from "vitest";
import { mockEntryAdviceChipEnvelope, mockEntryAdviceEnvelope } from "../../../fixtures/league";
import { CHIP_NAMES } from "../chipShape";
import { HttpAdviceClient, StaticOnlyAdviceClient, type AdviceRequest } from "./adviceClient";
import { adviceRequestKey } from "./adviceJobStore";
import { checkedAdvice } from "./adviceResponse";
import { sameAdviceRequest } from "./useAdviceJob";

const plain: AdviceRequest = {
  leagueId: 352490,
  entryId: 35249001,
  strategy: "saf-puan",
  window: 1,
};

it.each(CHIP_NAMES)("carries %s through GET and POST and keeps its job separate", async (chip) => {
  const request = { ...plain, chip };
  const envelope = mockEntryAdviceChipEnvelope(plain.entryId, chip);
  const transport = vi.fn(async () => new Response(JSON.stringify(envelope), { status: 200 }));
  const client = new HttpAdviceClient("https://api.example", transport);
  await expect(client.readAdvice(request)).resolves.toMatchObject({ kind: "advice", envelope });
  await expect(client.requestAdvice(request)).resolves.toMatchObject({ kind: "advice", envelope });
  const calls = transport.mock.calls as unknown as [string, RequestInit][];
  expect(calls[0]![0]).toContain(`&chip=${chip}`);
  expect(JSON.parse(calls[1]![1].body as string)).toMatchObject({ chip });
  expect(adviceRequestKey(request)).not.toBe(adviceRequestKey(plain));
  expect(sameAdviceRequest(request, plain)).toBe(false);
  expect(() =>
    checkedAdvice(mockEntryAdviceEnvelope(plain.entryId, "saf-puan", 1), request),
  ).toThrow();
  expect(() => checkedAdvice(envelope, { ...plain, chip: null })).toThrow();
  const other = CHIP_NAMES.find((name) => name !== chip)!;
  expect(() => checkedAdvice(envelope, { ...plain, chip: other })).toThrow();
  const loader = vi.fn(async () => envelope);
  await expect(new StaticOnlyAdviceClient(loader).readAdvice(request)).resolves.toEqual({
    kind: "not-computed",
  });
  expect(loader).not.toHaveBeenCalled();
});

it("preserves the existing plain job key and distinguishes all four chips", () => {
  expect(adviceRequestKey({ ...plain, chip: null })).toBe(adviceRequestKey(plain));
  expect(sameAdviceRequest({ ...plain, chip: null }, plain)).toBe(true);
  expect(new Set(CHIP_NAMES.map((chip) => adviceRequestKey({ ...plain, chip }))).size).toBe(4);
});
