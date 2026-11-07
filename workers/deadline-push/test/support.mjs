// What the tests build their worlds from: a subscriber with real keys, a fixtures_v1 list with
// chosen deadlines, a recording fetch, and a clock. No network, no credentials.

import { fromBase64Url, toBase64Url } from "../src/webpush.js";

export const SITE = "https://squadopt.mymandev.com";
export const PUSH_SERVICE = "https://push.example.net/send/";

/** 2026-11-21T08:00:00Z: three hours and ten minutes before GW11's deadline below. */
export const NOW_MS = Date.parse("2026-11-21T07:50:00Z");
export const GW11_DEADLINE = "2026-11-21T11:00:00Z";

export function testClock(start = NOW_MS) {
  let current = start;
  return {
    now: () => current,
    advance(ms) {
      current += ms;
    },
  };
}

/** A fixtures_v1 document with the deadlines the test names. */
export function fixturesJson(deadlines = { 10: "2026-11-06T18:30:00Z", 11: GW11_DEADLINE, 12: "2026-11-27T18:30:00Z" }) {
  return {
    contract_version: "fixtures_v1",
    generated_at_utc: "2026-11-20T06:00:00Z",
    source_kind: "live",
    payload: {
      season: "2026-27",
      source_snapshot_id: "fpl-live-20261120T060000Z-abcdefabcdef",
      captured_at_utc: "2026-11-20T06:00:00Z",
      current_gameweek: 10,
      unscheduled_count: 0,
      gameweeks: Object.entries(deadlines).map(([gameweek, deadline_utc]) => ({
        gameweek: Number(gameweek),
        deadline_utc,
        fixtures: [],
      })),
    },
  };
}

/** A browser's subscription: a real P-256 key pair and a 16-byte auth secret, keys kept for decrypting. */
export async function subscriber(suffix = "a", { language = "tr", league_id = 352490, entry_id = 35249001 } = {}) {
  const pair = await crypto.subtle.generateKey({ name: "ECDH", namedCurve: "P-256" }, true, ["deriveBits"]);
  const point = new Uint8Array(await crypto.subtle.exportKey("raw", pair.publicKey));
  const auth = crypto.getRandomValues(new Uint8Array(16));
  return {
    pair,
    body: {
      contract_version: "push_subscription_v1",
      endpoint: `${PUSH_SERVICE}${suffix}`,
      keys: { p256dh: toBase64Url(point), auth: toBase64Url(auth) },
      language,
      league_id,
      entry_id,
    },
  };
}

const encoder = new TextEncoder();

function concat(...parts) {
  const out = new Uint8Array(parts.reduce((sum, part) => sum + part.byteLength, 0));
  let offset = 0;
  for (const part of parts) {
    out.set(new Uint8Array(part), offset);
    offset += part.byteLength;
  }
  return out;
}

async function hkdf(salt, ikm, info, length) {
  const key = await crypto.subtle.importKey("raw", ikm, "HKDF", false, ["deriveBits"]);
  return new Uint8Array(
    await crypto.subtle.deriveBits({ name: "HKDF", hash: "SHA-256", salt, info }, key, length * 8),
  );
}

/** The receiving side of RFC 8291, as a browser's push service client decrypts a message. */
export async function decryptMessage(bytes, { pair, body }) {
  const salt = bytes.slice(0, 16);
  const recordSize = new DataView(bytes.buffer, bytes.byteOffset + 16, 4).getUint32(0);
  const idLength = bytes[20];
  const senderPoint = bytes.slice(21, 21 + idLength);
  const cipher = bytes.slice(21 + idLength);
  const senderKey = await crypto.subtle.importKey("raw", senderPoint, { name: "ECDH", namedCurve: "P-256" }, false, []);
  const shared = new Uint8Array(
    await crypto.subtle.deriveBits({ name: "ECDH", public: senderKey }, pair.privateKey, 256),
  );
  const receiverPoint = fromBase64Url(body.keys.p256dh);
  const authSecret = fromBase64Url(body.keys.auth);
  const ikm = await hkdf(authSecret, shared, concat(encoder.encode("WebPush: info\0"), receiverPoint, senderPoint), 32);
  const contentKey = await hkdf(salt, ikm, encoder.encode("Content-Encoding: aes128gcm\0"), 16);
  const nonce = await hkdf(salt, ikm, encoder.encode("Content-Encoding: nonce\0"), 12);
  const aesKey = await crypto.subtle.importKey("raw", contentKey, "AES-GCM", false, ["decrypt"]);
  const plain = new Uint8Array(await crypto.subtle.decrypt({ name: "AES-GCM", iv: nonce }, aesKey, cipher));
  const delimiter = plain.at(-1);
  return { recordSize, delimiter, text: new TextDecoder().decode(plain.slice(0, -1)) };
}

/** A VAPID key pair as the deploy keeps it: the private scalar and the public point, base64url. */
export async function vapidPair() {
  const pair = await crypto.subtle.generateKey({ name: "ECDSA", namedCurve: "P-256" }, true, ["sign", "verify"]);
  const jwk = await crypto.subtle.exportKey("jwk", pair.privateKey);
  const point = new Uint8Array(await crypto.subtle.exportKey("raw", pair.publicKey));
  return { privateKey: jwk.d, publicKey: toBase64Url(point), verifyKey: pair.publicKey };
}

/**
 * A fetch that answers the site's fixture list and every push service POST, recording each
 * push. `pushStatus` may be a number or a function of the request.
 */
export function fakeFetch({ fixtures = fixturesJson(), pushStatus = 201, fixturesStatus = 200 } = {}) {
  const pushes = [];
  const calls = [];
  const fetchImpl = async (input, init = {}) => {
    const request = input instanceof Request ? input : new Request(input, init);
    calls.push(request.url);
    if (request.url === `${SITE}/data/fixtures.json`) {
      return fixturesStatus === 200
        ? Response.json(fixtures)
        : new Response("", { status: fixturesStatus });
    }
    if (request.url.startsWith(PUSH_SERVICE)) {
      const body = new Uint8Array(await request.arrayBuffer());
      pushes.push({ url: request.url, headers: Object.fromEntries(request.headers), body });
      const status = typeof pushStatus === "function" ? pushStatus(request) : pushStatus;
      return new Response(null, { status });
    }
    throw new Error(`unexpected fetch ${request.url}`);
  };
  return { pushes, calls, fetchImpl };
}
