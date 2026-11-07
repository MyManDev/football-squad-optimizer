// The rules alone: what a subscription must carry, which week a run reminds of, what the
// notification says. The request's examples are held to the committed contract schema.

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { contractFile, problems } from "../../fpl-proxy/test/schema.mjs";
import {
  REMIND_BEFORE_MS,
  RefusedError,
  deadlinesFrom,
  endpointFrom,
  message,
  payloadFor,
  subscriptionFrom,
  subscriptionGone,
  targetPath,
  windowGameweek,
} from "../src/rules.js";
import { GW11_DEADLINE, NOW_MS, fixturesJson, subscriber } from "./support.mjs";

const refuses = (fn, reason) =>
  assert.throws(fn, (error) => error instanceof RefusedError && error.reason === reason, reason);

describe("a subscription request", () => {
  it("is read when it carries the contract, an https endpoint, both keys, a language and the ids", async () => {
    const { body } = await subscriber();
    assert.deepEqual(subscriptionFrom(body), {
      endpoint: body.endpoint,
      p256dh: body.keys.p256dh,
      auth: body.keys.auth,
      language: "tr",
      league_id: 352490,
      entry_id: 35249001,
    });
    // A team on its own: league 0.
    assert.equal(subscriptionFrom({ ...body, league_id: 0 }).league_id, 0);
  });

  it("names the first thing wrong with a request", async () => {
    const { body } = await subscriber();
    refuses(() => subscriptionFrom(null), "body_not_object");
    refuses(() => subscriptionFrom({ ...body, contract_version: "push_subscription_v2" }), "wrong_contract");
    refuses(() => subscriptionFrom({ ...body, endpoint: "not a url" }), "endpoint_not_url");
    refuses(() => subscriptionFrom({ ...body, endpoint: "http://push.example.net/x" }), "endpoint_refused");
    refuses(() => subscriptionFrom({ ...body, keys: undefined }), "keys_missing");
    refuses(() => subscriptionFrom({ ...body, keys: { ...body.keys, p256dh: "short" } }), "p256dh_refused");
    refuses(() => subscriptionFrom({ ...body, keys: { ...body.keys, auth: "has+plus/and=padding" } }), "auth_refused");
    refuses(() => subscriptionFrom({ ...body, language: "de" }), "language_refused");
    refuses(() => subscriptionFrom({ ...body, league_id: -1 }), "league_id_refused");
    refuses(() => subscriptionFrom({ ...body, entry_id: 1.5 }), "entry_id_refused");
    refuses(() => subscriptionFrom({ ...body, entry_id: 0 }), "entry_id_refused");
  });

  it("matches the committed contract: its examples pass the schema, a stripped one does not", async () => {
    const schema = await contractFile("push_subscription_v1.schema.json");
    const examples = await contractFile("push_subscription_v1.examples.json");
    assert.ok(Object.keys(examples).length >= 2);
    for (const [name, example] of Object.entries(examples)) {
      assert.deepEqual(problems(schema, example), [], name);
      assert.doesNotThrow(() => subscriptionFrom(example), name);
    }
    const { keys, ...withoutKeys } = examples.league_member;
    assert.notDeepEqual(problems(schema, withoutKeys), []);
    assert.notDeepEqual(problems(schema, { ...examples.league_member, extra: 1 }), []);
  });

  it("reads the endpoint a removal names", () => {
    assert.equal(endpointFrom({ endpoint: "https://push.example.net/x" }), "https://push.example.net/x");
    refuses(() => endpointFrom({}), "endpoint_missing");
    refuses(() => endpointFrom({ endpoint: "ftp://x" }), "endpoint_refused");
  });
});

describe("which week a run reminds of", () => {
  const deadlines = deadlinesFrom(fixturesJson());

  it("reads the deadlines in time order from the site's fixture list", () => {
    assert.deepEqual(
      deadlines.map((d) => d.gameweek),
      [10, 11, 12],
    );
    assert.equal(deadlines[1].deadlineMs, Date.parse(GW11_DEADLINE));
    refuses(() => deadlinesFrom({ contract_version: "fixtures_v2" }), "fixtures_not_v1");
    refuses(() => deadlinesFrom({ ...fixturesJson(), payload: { gameweeks: [{ gameweek: 1 }] } }), "fixtures_unreadable");
  });

  it("is the week whose deadline is ahead and within three hours, else none", () => {
    const deadline = Date.parse(GW11_DEADLINE);
    assert.equal(windowGameweek(deadlines, deadline - REMIND_BEFORE_MS - 1), null);
    assert.equal(windowGameweek(deadlines, deadline - REMIND_BEFORE_MS)?.gameweek, 11);
    assert.equal(windowGameweek(deadlines, deadline - 60_000)?.gameweek, 11);
    assert.equal(windowGameweek(deadlines, deadline), null);
    // Between deadlines, nothing; a past deadline never counts.
    assert.equal(windowGameweek(deadlines, NOW_MS - 86_400_000), null);
  });
});

describe("the notification", () => {
  it("says the week and the three hours in the subscriber's language, and opens their page", async () => {
    assert.deepEqual(message(11, "tr"), { title: "GW11: son 3 saat", body: "Planın hazır." });
    assert.deepEqual(message(11, "en"), { title: "GW11: 3 hours left", body: "Your plan is ready." });
    const { body } = await subscriber();
    const member = subscriptionFrom(body);
    assert.equal(targetPath(member), "/league/352490/members/35249001");
    assert.equal(targetPath({ ...member, league_id: 0 }), "/entry/35249001");
    assert.deepEqual(payloadFor(11, member), {
      title: "GW11: son 3 saat",
      body: "Planın hazır.",
      url: "https://squadopt.mymandev.com/league/352490/members/35249001",
      gameweek: 11,
    });
  });

  it("knows which push service answers mean the subscription is gone", () => {
    assert.equal(subscriptionGone(404), true);
    assert.equal(subscriptionGone(410), true);
    assert.equal(subscriptionGone(429), false);
    assert.equal(subscriptionGone(500), false);
  });
});
