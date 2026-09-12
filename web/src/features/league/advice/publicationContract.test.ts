/// <reference types="node" />
// @vitest-environment node
import { readFileSync } from "node:fs";
import { expect, it } from "vitest";
import { checkedAdvice } from "./adviceResponse";
import type { AdviceRequest } from "./adviceClient";
import type { EntryAdviceIndex, LeagueViewEnvelope } from "../types";

const fixture = process.env.SQUADOPT_PUBLICATION_FIXTURE;

it.skipIf(!fixture)("accepts the Python publisher and every declared index address", () => {
  const documents = JSON.parse(readFileSync(fixture!, "utf-8")) as {
    path: string;
    document: unknown;
  }[];
  const byPath = new Map(documents.map((item) => [item.path, item.document]));
  let adviceCount = 0;
  let indexCount = 0;
  for (const item of documents) {
    const match = /^advice\/(\d+)\/([^/]+)\/(1|3|5)(?:\/vs-(\d+))?\.json$/.exec(item.path);
    if (match) {
      const envelope = checkedAdvice(item.document, {
        leagueId: 352490,
        entryId: Number(match[1]),
        strategy: match[2] as AdviceRequest["strategy"],
        window: Number(match[3]) as AdviceRequest["window"],
        rivalEntryId: match[4] ? Number(match[4]) : undefined,
      });
      expect(envelope.source_kind).toBe("live");
      expect(envelope.payload.moves.length).toBeGreaterThanOrEqual(0);
      adviceCount += 1;
    }
    if (/^advice\/\d+\/index.json$/.test(item.path)) {
      const { payload: index } = item.document as LeagueViewEnvelope<EntryAdviceIndex>;
      expect(item.path).toBe(`advice/${index.entry_id}/index.json`);
      for (const entry of index.computed) {
        expect(byPath.has(entry.path), entry.path).toBe(true);
        checkedAdvice(byPath.get(entry.path), {
          leagueId: index.league_id,
          season: index.season,
          gameweek: index.gameweek,
          entryId: index.entry_id,
          strategy: entry.strategy as AdviceRequest["strategy"],
          window: 1,
          rivalEntryId: entry.rival_entry_id,
        });
      }
      for (const window of index.windows?.["saf-puan"] ?? [1]) {
        expect(byPath.has(`advice/${index.entry_id}/saf-puan/${window}.json`)).toBe(true);
      }
      indexCount += 1;
    }
  }
  expect(indexCount).toBe(2);
  expect(adviceCount).toBeGreaterThanOrEqual(6);
});
