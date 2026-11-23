// The report routes (ADR 0016) over a fake Access key set and a fake SQL API, both served by a
// fetch handed to the Worker: who gets the record, what they get, and what is never read, sent
// back or logged. The signing key is made here with WebCrypto; nothing touches the network.

import assert from "node:assert/strict";
import { before, describe, it } from "node:test";

import { KEYS_TTL_MS } from "../src/access.js";
import { MARKER_HEADER, MARKER_VALUE } from "../src/rules.js";
import { ADMIN_CONTRACT, ROW_LIMIT, buildReport, reportQuery } from "../src/report.js";
import { createWorker, routeFor } from "../src/worker.js";
import { SITE } from "./support.mjs";

const TEAM = "squadopt.cloudflareaccess.com";
const ISSUER = `https://${TEAM}`;
const CERTS = `${ISSUER}/cdn-cgi/access/certs`;
const AUDIENCE = "4714c1358e65fe4b408ad6d432a5f878f08194bdb4752441fd56faefa9b2b6f2";
const ACCOUNT = "0123456789abcdef0123456789abcdef";
const SQL_URL = `https://api.cloudflare.com/client/v4/accounts/${ACCOUNT}/analytics_engine/sql`;
const READ_TOKEN = "read-token-that-must-never-be-echoed";
const EMAIL = "owner@example.com";

const REPORT = "/api/v1/usage/report";
const ME = "/api/v1/usage/report/me";
const TODAY = "2026-11-16";
const START = Date.parse(`${TODAY}T12:00:00Z`);
const NOW_SECONDS = Math.floor(START / 1000);

const SETTINGS = {
  ACCESS_TEAM_DOMAIN: TEAM,
  ACCESS_AUD: AUDIENCE,
  ANALYTICS_ACCOUNT_ID: ACCOUNT,
  ANALYTICS_TOKEN: READ_TOKEN,
};

const ROWS = [
  { page: "member", tool: "week", step: "open", lang: "tr", device: "phone", session: "aaaaaaaaaaaaaaaa", detail1: "", detail2: "", detail3: "", v: 1, measure: 0, events: "2" },
  { page: "member", tool: "week", step: "click", lang: "tr", device: "phone", session: "aaaaaaaaaaaaaaaa", detail1: "decision", detail2: "control", detail3: "none", v: 2, measure: 47, events: "3" },
];

const RSA = { name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" };

const base64url = (bytes) => Buffer.from(bytes).toString("base64url");
const encode = (value) => base64url(new TextEncoder().encode(JSON.stringify(value)));

async function keyPair(kid) {
  const pair = await crypto.subtle.generateKey(RSA, true, ["sign", "verify"]);
  const jwk = await crypto.subtle.exportKey("jwk", pair.publicKey);
  // Access publishes `alg` and `use` beside the key's numbers.
  return { kid, privateKey: pair.privateKey, jwk: { ...jwk, kid, alg: "RS256", use: "sig" } };
}

async function sign(claims, { key, kid = key.kid, alg = "RS256" }) {
  const head = `${encode({ alg, kid, typ: "JWT" })}.${encode(claims)}`;
  const signature = await crypto.subtle.sign(RSA.name, key.privateKey, new TextEncoder().encode(head));
  return `${head}.${base64url(new Uint8Array(signature))}`;
}

const goodClaims = (overrides = {}) => ({
  aud: [AUDIENCE],
  email: EMAIL,
  exp: NOW_SECONDS + 3600,
  iat: NOW_SECONDS - 10,
  nbf: NOW_SECONDS - 10,
  iss: ISSUER,
  sub: "7335d417-61da-459d-899c-0a01c76a2f94",
  type: "app",
  identity_nonce: "6ei69kawdKzMIAPF",
  country: "TR",
  ...overrides,
});

let primary;
let other;
let rotated;

before(async () => {
  primary = await keyPair("key-one");
  other = await keyPair("key-other");
  rotated = await keyPair("key-two");
});

/**
 * A Worker over a fetch that serves the key set and the SQL API, recording every call, and a
 * clock the test can move.
 */
function harness({ env = SETTINGS, keys = () => [primary.jwk], sql } = {}) {
  const calls = [];
  const lines = [];
  const clock = { now: START };
  const answerSql = sql ?? (() => Response.json({ meta: [], data: ROWS, rows: ROWS.length }));
  const fetch = async (input, init = {}) => {
    const url = String(input);
    calls.push({ url, init });
    if (url === CERTS) {
      const published = keys();
      if (published === null) return new Response("unavailable", { status: 503 });
      return Response.json({ keys: published, public_cert: { kid: "x", cert: "" }, public_certs: [] });
    }
    if (url === SQL_URL) return answerSql(init);
    throw new Error(`no such address in the test: ${url}`);
  };
  const worker = createWorker({ fetch, now: () => clock.now, log: (event, fields) => lines.push({ event, ...fields }) });
  const send = (path, { token, method = "GET", headers = {} } = {}) =>
    worker.fetch(
      new Request(`${SITE}${path}`, {
        method,
        headers: { ...(token === undefined ? {} : { "cf-access-jwt-assertion": token }), ...headers },
      }),
      { USAGE_EVENTS: { writeDataPoint: () => {} }, ...env },
    );
  const certsCalls = () => calls.filter((call) => call.url === CERTS).length;
  const sqlCalls = () => calls.filter((call) => call.url === SQL_URL);
  return { calls, certsCalls, clock, lines, send, sqlCalls };
}

const range = (from, to) => `${REPORT}?from=${from}&to=${to}`;

function assertPrivate(response) {
  assert.equal(response.headers.get("cache-control"), "private, no-store");
  assert.match(response.headers.get("content-type"), /^application\/json/);
  assert.equal(response.headers.get(MARKER_HEADER), MARKER_VALUE);
  assert.equal(response.headers.get("access-control-allow-origin"), null);
}

describe("the report's paths", () => {
  it("are two routes of their own", () => {
    assert.equal(routeFor(REPORT), "report");
    assert.equal(routeFor(ME), "report_me");
    assert.equal(routeFor(`${REPORT}/`), null);
    assert.equal(routeFor(`${ME}/x`), null);
  });
});

describe("a signed-in admin", () => {
  it("gets the report for the range, read with the SQL the script sends", async () => {
    const { send, sqlCalls } = harness();
    const token = await sign(goodClaims(), { key: primary });
    const response = await send(range("2026-11-01", TODAY), { token });
    assert.equal(response.status, 200);
    assertPrivate(response);
    assert.deepEqual(await response.json(), buildReport({ from: "2026-11-01", to: TODAY, truncated: false, rows: ROWS }));
    const [call] = sqlCalls();
    assert.equal(sqlCalls().length, 1);
    assert.equal(call.init.method, "POST");
    assert.equal(call.init.headers.authorization, `Bearer ${READ_TOKEN}`);
    assert.equal(call.init.body, reportQuery("2026-11-01", TODAY));
  });

  it("is told when the row limit cut the range off", async () => {
    const full = Array.from({ length: ROW_LIMIT }, (_, index) => ROWS[index % ROWS.length]);
    const { send } = harness({ sql: () => Response.json({ data: full, rows_before_limit_at_least: 500_000 }) });
    const response = await send(range(TODAY, TODAY), { token: await sign(goodClaims(), { key: primary }) });
    assert.equal((await response.json()).truncated, true);
  });

  it("is an admin to /report/me, which reads nothing", async () => {
    const { send, sqlCalls } = harness();
    const response = await send(ME, { token: await sign(goodClaims(), { key: primary }) });
    assert.equal(response.status, 200);
    assertPrivate(response);
    assert.deepEqual(await response.json(), { contract_version: ADMIN_CONTRACT, admin: true });
    assert.equal(ADMIN_CONTRACT, "usage_admin_v1");
    assert.equal(sqlCalls().length, 0);
  });

  it("is let in with a single audience, a team written as an address, and a clock a little off", async () => {
    const env = { ...SETTINGS, ACCESS_TEAM_DOMAIN: `https://${TEAM}/` };
    const { calls, send } = harness({ env });
    const claims = goodClaims({ aud: AUDIENCE, exp: NOW_SECONDS - 30, nbf: NOW_SECONDS + 30, iat: NOW_SECONDS + 30 });
    const response = await send(ME, { token: await sign(claims, { key: primary }) });
    assert.equal(response.status, 200);
    assert.equal(calls[0].url, CERTS);
  });

  it("can use only GET", async () => {
    const { send, sqlCalls } = harness();
    const token = await sign(goodClaims(), { key: primary });
    for (const path of [range(TODAY, TODAY), ME]) {
      const response = await send(path, { token, method: "POST" });
      assert.equal(response.status, 405);
      assertPrivate(response);
      assert.deepEqual(await response.json(), { error: "method_not_allowed" });
    }
    assert.equal(sqlCalls().length, 0);
  });
});

describe("a request without a valid sign-in", () => {
  const refusals = {
    "no header": async () => undefined,
    "an empty header": async () => "",
    "not a token": async () => "not.a-token",
    "a bad signature": () => sign(goodClaims(), { key: other, kid: primary.kid }),
    "an altered claim": async () => {
      const [head, , signature] = (await sign(goodClaims(), { key: primary })).split(".");
      return `${head}.${encode(goodClaims({ email: "someone@example.com" }))}.${signature}`;
    },
    "another algorithm": () => sign(goodClaims(), { key: primary, alg: "RS512" }),
    "the wrong audience": () => sign(goodClaims({ aud: ["another-application"] }), { key: primary }),
    "no audience": () => sign(goodClaims({ aud: undefined }), { key: primary }),
    "the wrong issuer": () => sign(goodClaims({ iss: "https://other.cloudflareaccess.com" }), { key: primary }),
    "an expired token": () => sign(goodClaims({ exp: NOW_SECONDS - 61 }), { key: primary }),
    "no expiry": () => sign(goodClaims({ exp: undefined }), { key: primary }),
    "a token not yet valid": () => sign(goodClaims({ nbf: NOW_SECONDS + 120 }), { key: primary }),
    "a token issued in the future": () => sign(goodClaims({ iat: NOW_SECONDS + 120 }), { key: primary }),
    "an unknown key": () => sign(goodClaims(), { key: other }),
  };

  for (const [name, make] of Object.entries(refusals)) {
    it(`is refused with ${name}, and nothing is read`, async () => {
      const { send, sqlCalls } = harness();
      const token = await make();
      for (const path of [range(TODAY, TODAY), ME]) {
        const response = await send(path, { token });
        assert.equal(response.status, 403, `${name} ${path}`);
        assertPrivate(response);
        assert.deepEqual(await response.json(), { error: "access_refused" });
      }
      assert.equal(sqlCalls().length, 0);
    });
  }

  it("is refused when the key set cannot be read, which is then not kept", async () => {
    let up = false;
    const { send, certsCalls } = harness({ keys: () => (up ? [primary.jwk] : null) });
    const token = await sign(goodClaims(), { key: primary });
    assert.equal((await send(ME, { token })).status, 403);
    up = true;
    assert.equal((await send(ME, { token })).status, 200);
    assert.equal(certsCalls(), 2);
  });

  it("is refused before the range is looked at", async () => {
    const { send } = harness();
    const response = await send(`${REPORT}?from=nonsense`, {});
    assert.equal(response.status, 403);
  });
});

describe("the team's keys", () => {
  it("are read once and kept for ten minutes", async () => {
    const { certsCalls, clock, send } = harness();
    const token = await sign(goodClaims({ exp: NOW_SECONDS + 7200 }), { key: primary });
    for (let index = 0; index < 3; index += 1) assert.equal((await send(ME, { token })).status, 200);
    assert.equal(certsCalls(), 1);
    clock.now += KEYS_TTL_MS - 1;
    assert.equal((await send(ME, { token })).status, 200);
    assert.equal(certsCalls(), 1);
    clock.now += 1;
    assert.equal((await send(ME, { token })).status, 200);
    assert.equal(certsCalls(), 2);
    assert.equal(KEYS_TTL_MS, 600_000);
  });

  it("are read once more for a key they do not hold, and the token refused if it is still unknown", async () => {
    const { certsCalls, send, sqlCalls } = harness();
    assert.equal((await send(ME, { token: await sign(goodClaims(), { key: primary }) })).status, 200);
    assert.equal(certsCalls(), 1);
    const response = await send(range(TODAY, TODAY), { token: await sign(goodClaims(), { key: other }) });
    assert.equal(response.status, 403);
    assert.equal(certsCalls(), 2);
    assert.equal(sqlCalls().length, 0);
  });

  it("follow a rotation: a token under the new key reads the set again and is let in", async () => {
    let published = [primary.jwk];
    const { certsCalls, send } = harness({ keys: () => published });
    assert.equal((await send(ME, { token: await sign(goodClaims(), { key: primary }) })).status, 200);
    published = [primary.jwk, rotated.jwk];
    assert.equal((await send(ME, { token: await sign(goodClaims(), { key: rotated }) })).status, 200);
    assert.equal(certsCalls(), 2);
    assert.equal((await send(ME, { token: await sign(goodClaims(), { key: rotated }) })).status, 200);
    assert.equal(certsCalls(), 2);
  });
});

describe("a Worker without its settings", () => {
  for (const missing of Object.keys(SETTINGS)) {
    it(`answers 503 without ${missing}, before it looks at the sign-in`, async () => {
      const env = { ...SETTINGS, [missing]: "" };
      const { calls, send } = harness({ env });
      const token = await sign(goodClaims(), { key: primary });
      for (const path of [range(TODAY, TODAY), ME]) {
        for (const request of [{ token }, {}]) {
          const response = await send(path, request);
          assert.equal(response.status, 503);
          assertPrivate(response);
          assert.deepEqual(await response.json(), { error: "report_not_configured" });
        }
      }
      assert.equal(calls.length, 0);
    });
  }

  it("answers 503 when a setting is absent rather than empty", async () => {
    const { ANALYTICS_TOKEN: _token, ...env } = SETTINGS;
    const response = await harness({ env }).send(ME, {});
    assert.equal(response.status, 503);
  });
});

describe("the range", () => {
  const cases = [
    [`${REPORT}`, "from_not_a_date"],
    [`${REPORT}?to=${TODAY}`, "from_not_a_date"],
    [range("2026-11-1", TODAY), "from_not_a_date"],
    [range("2026-02-30", TODAY), "from_not_a_date"],
    [`${REPORT}?from=2026-11-01`, "to_not_a_date"],
    [range("2026-11-01", "today"), "to_not_a_date"],
    [range("2026-11-10", "2026-11-01"), "from_after_to"],
    [range("2026-08-16", TODAY), "range_too_long"],
    [range("2026-11-01", "2026-11-17"), "to_in_future"],
  ];

  it("is refused with a named reason, and nothing is read", async () => {
    const { send, sqlCalls } = harness();
    const token = await sign(goodClaims(), { key: primary });
    for (const [path, reason] of cases) {
      const response = await send(path, { token });
      assert.equal(response.status, 400, path);
      assertPrivate(response);
      assert.deepEqual(await response.json(), { error: reason }, path);
    }
    assert.equal(sqlCalls().length, 0);
  });

  it("may be 92 days ending today", async () => {
    const { send } = harness();
    const response = await send(range("2026-08-17", TODAY), { token: await sign(goodClaims(), { key: primary }) });
    assert.equal(response.status, 200);
  });
});

describe("Analytics Engine failing", () => {
  const failures = {
    "a 500 that echoes the request": () => new Response(`bad request with Bearer ${READ_TOKEN}`, { status: 500 }),
    "a 403": () => Response.json({ errors: [{ message: `token ${READ_TOKEN} lacks permission` }] }, { status: 403 }),
    "an answer that is not JSON": () => new Response("<html>gateway</html>"),
    "an answer without rows": () => Response.json({ meta: [] }),
    "no answer at all": () => {
      throw new TypeError(`fetch failed for ${READ_TOKEN}`);
    },
  };

  for (const [name, sql] of Object.entries(failures)) {
    it(`gives 502 on ${name}, with neither the token nor the upstream body in the answer or the logs`, async () => {
      const { lines, send } = harness({ sql });
      const response = await send(range("2026-11-01", TODAY), { token: await sign(goodClaims(), { key: primary }) });
      assert.equal(response.status, 502);
      assertPrivate(response);
      const body = await response.text();
      assert.deepEqual(JSON.parse(body), { error: "analytics_unavailable" });
      const logged = JSON.stringify(lines);
      for (const text of [READ_TOKEN, "gateway", "permission", "Bearer"]) {
        assert.equal(body.includes(text), false, text);
        assert.equal(logged.includes(text), false, text);
      }
      assert.ok(lines.some((line) => line.event === "analytics_failed"));
    });
  }
});

describe("the logs", () => {
  it("hold no token, no sign-in and no email, whatever happens", async () => {
    const { lines, send } = harness();
    const good = await sign(goodClaims(), { key: primary });
    const tokens = [
      good,
      await sign(goodClaims({ aud: "elsewhere" }), { key: primary }),
      await sign(goodClaims(), { key: other }),
    ];
    for (const token of tokens) {
      await send(range("2026-11-01", TODAY), { token });
      await send(ME, { token });
    }
    const logged = JSON.stringify(lines);
    for (const text of [READ_TOKEN, EMAIL, ...tokens, ...tokens.map((token) => token.split(".")[1])]) {
      assert.equal(logged.includes(text), false);
    }
    assert.deepEqual(
      lines.map((line) => Object.keys(line).sort().join(",")),
      lines.map(() => "event,reason"),
    );
  });
});
