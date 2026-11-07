// The protocol: a message the Worker encrypts is one a subscriber decrypts to the same text,
// and the VAPID header it signs verifies with the public key it names.

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  encryptMessage,
  fromBase64Url,
  importVapidKey,
  pushRequest,
  toBase64Url,
  vapidAuthorization,
} from "../src/webpush.js";
import { NOW_MS, decryptMessage, subscriber, vapidPair } from "./support.mjs";

describe("base64url", () => {
  it("round-trips bytes without padding or the standard alphabet", () => {
    const bytes = new Uint8Array([0, 1, 2, 250, 251, 252, 253, 254, 255]);
    const text = toBase64Url(bytes);
    assert.doesNotMatch(text, /[+/=]/);
    assert.deepEqual(fromBase64Url(text), bytes);
  });
});

describe("the aes128gcm message", () => {
  it("decrypts on the subscriber's side to the text sent, in one record with the final delimiter", async () => {
    const who = await subscriber();
    const payload = JSON.stringify({ title: "GW11: son 3 saat", body: "Planın hazır." });
    const bytes = await encryptMessage(payload, who.body.keys);
    const { recordSize, delimiter, text } = await decryptMessage(bytes, who);
    assert.equal(recordSize, 4096);
    assert.equal(delimiter, 2);
    assert.equal(text, payload);
    // Header: 16 salt + 4 rs + 1 idlen + 65 key; then the ciphertext with its 16-byte tag.
    assert.equal(bytes.length, 86 + new TextEncoder().encode(payload).length + 1 + 16);
  });

  it("never encrypts two messages alike: a fresh key and salt each time", async () => {
    const who = await subscriber();
    const first = await encryptMessage("x", who.body.keys);
    const second = await encryptMessage("x", who.body.keys);
    assert.notDeepEqual(first.slice(0, 16), second.slice(0, 16));
    assert.notDeepEqual(first.slice(21, 86), second.slice(21, 86));
  });

  it("refuses keys that are not a P-256 point and a 16-byte secret", async () => {
    const who = await subscriber();
    await assert.rejects(encryptMessage("x", { p256dh: toBase64Url(new Uint8Array(64)), auth: who.body.keys.auth }), /P-256/);
    await assert.rejects(encryptMessage("x", { p256dh: who.body.keys.p256dh, auth: toBase64Url(new Uint8Array(8)) }), /16 bytes/);
  });
});

describe("the VAPID header", () => {
  it("signs a JWT for the push service's origin that its public key verifies", async () => {
    const vapid = await vapidPair();
    const signingKey = await importVapidKey(vapid.privateKey, vapid.publicKey);
    const header = await vapidAuthorization({
      endpoint: "https://push.example.net/send/abc?x=1",
      signingKey,
      publicKey: vapid.publicKey,
      subject: "https://squadopt.mymandev.com",
      nowMs: NOW_MS,
    });
    const match = /^vapid t=([^,]+), k=(.+)$/.exec(header);
    assert.ok(match, header);
    assert.equal(match[2], vapid.publicKey);
    const [head, claims, signature] = match[1].split(".");
    const decode = (part) => JSON.parse(new TextDecoder().decode(fromBase64Url(part)));
    assert.deepEqual(decode(head), { typ: "JWT", alg: "ES256" });
    assert.deepEqual(decode(claims), {
      aud: "https://push.example.net",
      exp: Math.floor(NOW_MS / 1000) + 12 * 3600,
      sub: "https://squadopt.mymandev.com",
    });
    const verified = await crypto.subtle.verify(
      { name: "ECDSA", hash: "SHA-256" },
      vapid.verifyKey,
      fromBase64Url(signature),
      new TextEncoder().encode(`${head}.${claims}`),
    );
    assert.equal(verified, true);
  });

  it("refuses a private scalar or public point of the wrong size", async () => {
    const vapid = await vapidPair();
    await assert.rejects(importVapidKey(toBase64Url(new Uint8Array(31)), vapid.publicKey), /32 bytes/);
    await assert.rejects(importVapidKey(vapid.privateKey, toBase64Url(new Uint8Array(65))), /P-256/);
  });
});

describe("the push request", () => {
  it("posts the encrypted body with the encoding, the TTL and the VAPID header", async () => {
    const who = await subscriber();
    const vapid = await vapidPair();
    const request = await pushRequest({
      subscription: { endpoint: who.body.endpoint, ...who.body.keys },
      payload: "hello",
      vapid: { signingKey: await importVapidKey(vapid.privateKey, vapid.publicKey), publicKey: vapid.publicKey, subject: "mailto:x@example.com" },
      nowMs: NOW_MS,
      ttlSeconds: 10800,
    });
    assert.equal(request.method, "POST");
    assert.equal(request.url, who.body.endpoint);
    assert.equal(request.headers.get("content-encoding"), "aes128gcm");
    assert.equal(request.headers.get("content-type"), "application/octet-stream");
    assert.equal(request.headers.get("ttl"), "10800");
    assert.match(request.headers.get("authorization"), /^vapid t=/);
    const { text } = await decryptMessage(new Uint8Array(await request.arrayBuffer()), who);
    assert.equal(text, "hello");
  });
});
