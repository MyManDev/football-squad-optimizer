// Web Push without a dependency: the VAPID header (RFC 8292) and the aes128gcm message
// encryption (RFC 8291, RFC 8188), both on WebCrypto, which the Workers runtime and Node 22
// share. Nothing here reads the network; worker.js posts what these functions return.

const encoder = new TextEncoder();

export function toBase64Url(bytes) {
  let text = "";
  for (const byte of new Uint8Array(bytes)) text += String.fromCharCode(byte);
  return btoa(text).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function fromBase64Url(text) {
  const padded = text.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(text.length / 4) * 4, "=");
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}

function concat(...parts) {
  const length = parts.reduce((sum, part) => sum + part.byteLength, 0);
  const out = new Uint8Array(length);
  let offset = 0;
  for (const part of parts) {
    out.set(new Uint8Array(part), offset);
    offset += part.byteLength;
  }
  return out;
}

/** The uncompressed P-256 point (65 bytes) a base64url public key encodes, checked. */
function publicPoint(text, name) {
  const bytes = fromBase64Url(text);
  if (bytes.length !== 65 || bytes[0] !== 4) throw new Error(`${name} is not an uncompressed P-256 point`);
  return bytes;
}

/** The P-256 signing key a VAPID private scalar (base64url, 32 bytes) and its public point make. */
export async function importVapidKey(privateKey, publicKey) {
  const point = publicPoint(publicKey, "VAPID public key");
  const d = fromBase64Url(privateKey);
  if (d.length !== 32) throw new Error("VAPID private key is not 32 bytes");
  return crypto.subtle.importKey(
    "jwk",
    {
      kty: "EC",
      crv: "P-256",
      x: toBase64Url(point.slice(1, 33)),
      y: toBase64Url(point.slice(33, 65)),
      d: toBase64Url(d),
      ext: true,
    },
    { name: "ECDSA", namedCurve: "P-256" },
    false,
    ["sign"],
  );
}

/**
 * The Authorization header for one push service: a JWT for the endpoint's origin, signed with
 * the VAPID key, valid for twelve hours from `nowMs`, and the public key beside it.
 */
export async function vapidAuthorization({ endpoint, signingKey, publicKey, subject, nowMs }) {
  const audience = new URL(endpoint).origin;
  const header = toBase64Url(encoder.encode(JSON.stringify({ typ: "JWT", alg: "ES256" })));
  const claims = toBase64Url(
    encoder.encode(
      JSON.stringify({ aud: audience, exp: Math.floor(nowMs / 1000) + 12 * 3600, sub: subject }),
    ),
  );
  const signature = await crypto.subtle.sign(
    { name: "ECDSA", hash: "SHA-256" },
    signingKey,
    encoder.encode(`${header}.${claims}`),
  );
  return `vapid t=${header}.${claims}.${toBase64Url(signature)}, k=${publicKey}`;
}

async function hkdf(salt, ikm, info, length) {
  const key = await crypto.subtle.importKey("raw", ikm, "HKDF", false, ["deriveBits"]);
  return new Uint8Array(
    await crypto.subtle.deriveBits({ name: "HKDF", hash: "SHA-256", salt, info }, key, length * 8),
  );
}

/**
 * One message for one subscriber, encrypted as RFC 8291 says: an ephemeral P-256 key agreed
 * with the subscriber's `p256dh`, the subscriber's `auth` secret in the key derivation, a fresh
 * salt, and the aes128gcm body with its header. `payload` is text; the record is one.
 */
export async function encryptMessage(payload, { p256dh, auth }, randomness = crypto) {
  const subscriberPoint = publicPoint(p256dh, "p256dh");
  const authSecret = fromBase64Url(auth);
  if (authSecret.length !== 16) throw new Error("auth is not 16 bytes");
  const subscriberKey = await crypto.subtle.importKey(
    "raw",
    subscriberPoint,
    { name: "ECDH", namedCurve: "P-256" },
    false,
    [],
  );
  const ephemeral = await crypto.subtle.generateKey({ name: "ECDH", namedCurve: "P-256" }, true, [
    "deriveBits",
  ]);
  const ephemeralPoint = new Uint8Array(await crypto.subtle.exportKey("raw", ephemeral.publicKey));
  const shared = new Uint8Array(
    await crypto.subtle.deriveBits({ name: "ECDH", public: subscriberKey }, ephemeral.privateKey, 256),
  );
  const salt = randomness.getRandomValues(new Uint8Array(16));
  const keyInfo = concat(encoder.encode("WebPush: info\0"), subscriberPoint, ephemeralPoint);
  const ikm = await hkdf(authSecret, shared, keyInfo, 32);
  const contentKey = await hkdf(salt, ikm, encoder.encode("Content-Encoding: aes128gcm\0"), 16);
  const nonce = await hkdf(salt, ikm, encoder.encode("Content-Encoding: nonce\0"), 12);
  const aesKey = await crypto.subtle.importKey("raw", contentKey, "AES-GCM", false, ["encrypt"]);
  const plain = concat(encoder.encode(payload), new Uint8Array([2]));
  const cipher = new Uint8Array(
    await crypto.subtle.encrypt({ name: "AES-GCM", iv: nonce }, aesKey, plain),
  );
  const recordSize = new Uint8Array(4);
  new DataView(recordSize.buffer).setUint32(0, 4096);
  const header = concat(salt, recordSize, new Uint8Array([ephemeralPoint.length]), ephemeralPoint);
  return concat(header, cipher);
}

/**
 * The request that delivers one message to one push service: the encrypted body, the VAPID
 * header, the content encoding, and how long the service may hold it.
 */
export async function pushRequest({ subscription, payload, vapid, nowMs, ttlSeconds, randomness }) {
  const body = await encryptMessage(payload, subscription, randomness);
  const authorization = await vapidAuthorization({
    endpoint: subscription.endpoint,
    signingKey: vapid.signingKey,
    publicKey: vapid.publicKey,
    subject: vapid.subject,
    nowMs,
  });
  return new Request(subscription.endpoint, {
    method: "POST",
    headers: {
      authorization,
      "content-encoding": "aes128gcm",
      "content-type": "application/octet-stream",
      ttl: String(ttlSeconds),
      urgency: "normal",
    },
    body,
  });
}
