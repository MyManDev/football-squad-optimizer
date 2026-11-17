// The Cloudflare Access sign-in, checked by the Worker itself (ADR 0016). Access stands in front
// of the report's paths, but a misconfigured or missing Access application must expose nothing,
// so the Worker reads no analytics until the request carries a token that Access signed for this
// application: RS256 under a key of the team's published set, naming the application's audience
// tag and the team as issuer, and inside its time window.
//
// Nothing here logs or returns the token or any claim in it; a refusal says only which check
// failed, as a word.

/** The header Access adds to every request it lets through. */
export const ACCESS_HEADER = "cf-access-jwt-assertion";

/** How far apart Cloudflare's clock and this Worker's may be, in seconds. */
export const CLOCK_SKEW_SECONDS = 60;

/** How long the team's signing keys are kept in memory before they are read again. */
export const KEYS_TTL_MS = 10 * 60 * 1000;

const ALGORITHM = { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" };
const BASE64URL = /^[A-Za-z0-9_-]+$/;

/** A check that failed; `reason` is a fixed word, never anything from the request. */
export class AccessRefused extends Error {
  constructor(reason) {
    super(reason);
    this.name = "AccessRefused";
    this.reason = reason;
  }
}

/**
 * The team's host from the setting, which may be written as `team.cloudflareaccess.com`, with
 * `https://` before it or a slash after it; empty when nothing usable is left.
 */
export function teamHost(setting) {
  if (typeof setting !== "string") return "";
  const host = setting.trim().replace(/^https:\/\//i, "").replace(/\/+$/, "").toLowerCase();
  return /^[a-z0-9.-]+$/.test(host) ? host : "";
}

export const issuerFor = (host) => `https://${host}`;
export const certsUrlFor = (host) => `https://${host}/cdn-cgi/access/certs`;

function bytesFrom(part) {
  if (!BASE64URL.test(part)) throw new AccessRefused("malformed");
  const base64 = part.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(part.length / 4) * 4, "=");
  let binary;
  try {
    binary = atob(base64);
  } catch {
    throw new AccessRefused("malformed");
  }
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

function jsonFrom(part) {
  let value;
  try {
    value = JSON.parse(new TextDecoder().decode(bytesFrom(part)));
  } catch (error) {
    if (error instanceof AccessRefused) throw error;
    throw new AccessRefused("malformed");
  }
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw new AccessRefused("malformed");
  return value;
}

/** The claims Access promises, against the settings and the clock (seconds since 1970). */
function checkClaims(claims, { host, audience }, nowSeconds) {
  const audiences = typeof claims.aud === "string" ? [claims.aud] : Array.isArray(claims.aud) ? claims.aud : [];
  if (!audiences.includes(audience)) throw new AccessRefused("wrong_audience");
  if (claims.iss !== issuerFor(host)) throw new AccessRefused("wrong_issuer");
  if (typeof claims.exp !== "number" || claims.exp + CLOCK_SKEW_SECONDS <= nowSeconds) {
    throw new AccessRefused("expired");
  }
  for (const field of ["nbf", "iat"]) {
    if (claims[field] === undefined) continue;
    if (typeof claims[field] !== "number" || claims[field] - CLOCK_SKEW_SECONDS > nowSeconds) {
      throw new AccessRefused("not_yet_valid");
    }
  }
}

/**
 * The check, over the given fetch and clock. It keeps the team's keys in memory for KEYS_TTL_MS;
 * a token naming a key the kept set does not hold reads the set once more, since Access rotates
 * its keys, and is refused if the key is still not there.
 */
export function createAccessCheck({ fetch, now }) {
  let kept = null;

  async function readKeys(host) {
    let answer;
    try {
      const response = await fetch(certsUrlFor(host), { headers: { accept: "application/json" } });
      if (!response.ok) throw new Error("refused");
      answer = await response.json();
    } catch {
      throw new AccessRefused("keys_unavailable");
    }
    const keys = new Map();
    for (const jwk of Array.isArray(answer?.keys) ? answer.keys : []) {
      if (jwk?.kty !== "RSA" || typeof jwk.kid !== "string" || keys.has(jwk.kid)) continue;
      try {
        // Only the key's numbers are handed over, so a `use` or `key_ops` in the set cannot
        // make the import refuse a key that is fine for checking signatures.
        const key = await crypto.subtle.importKey("jwk", { kty: "RSA", n: jwk.n, e: jwk.e }, ALGORITHM, false, ["verify"]);
        keys.set(jwk.kid, key);
      } catch {
        // A key that does not import is one no token can be checked against; skip it.
      }
    }
    return { host, keys, readAt: now() };
  }

  async function keyFor(host, kid) {
    let fresh = false;
    if (kept === null || kept.host !== host || now() - kept.readAt >= KEYS_TTL_MS) {
      kept = await readKeys(host);
      fresh = true;
    }
    if (!kept.keys.has(kid) && !fresh) kept = await readKeys(host);
    return kept.keys.get(kid) ?? null;
  }

  /** Resolves when the token passes every check; throws AccessRefused naming the first that fails. */
  return async function verify(token, { host, audience }) {
    if (typeof token !== "string" || token === "") throw new AccessRefused("missing");
    const parts = token.split(".");
    if (parts.length !== 3) throw new AccessRefused("malformed");
    const header = jsonFrom(parts[0]);
    const claims = jsonFrom(parts[1]);
    const signature = bytesFrom(parts[2]);
    if (header.alg !== "RS256") throw new AccessRefused("wrong_algorithm");
    if (typeof header.kid !== "string" || header.kid === "") throw new AccessRefused("malformed");
    const key = await keyFor(host, header.kid);
    if (key === null) throw new AccessRefused("unknown_key");
    const signed = new TextEncoder().encode(`${parts[0]}.${parts[1]}`);
    let valid = false;
    try {
      valid = await crypto.subtle.verify(ALGORITHM, key, signature, signed);
    } catch {
      valid = false;
    }
    if (!valid) throw new AccessRefused("bad_signature");
    checkClaims(claims, { host, audience }, Math.floor(now() / 1000));
  };
}
