# ADR 0017: LLMOPT with the member's own model key, which the site never receives

- **Status:** proposed, for the owner's acceptance.
- **Date:** 2026-11-17
- **Decider:** the owner
- **Related:** [ADR 0006](0006-backend-hosting.md), [ADR 0012](0012-fpl-forwarder.md),
  [ADR 0014](0014-usage-measurement.md), issue #1430 (limits and the privacy line),
  `src/squadopt/platform/llmopt_intent.py`, `web/src/features/league/llmopt/`

## Context

LLMOPT turns a member's sentence into an editable draft of rules for the solver. Today the
backend makes that call with one site key (`SQUADOPT_LLMOPT_API_KEY`, Gemini). Every member's
text goes to the provider under the site's account, the site pays for it, and the whole site
shares a budget of 250 calls a day.

The owner's direction on 2026-11-17: members will connect their own model with their own API
key, and the site will not hold those keys. The keys must still be kept safely.

A key held by the site, even encrypted, makes the site a store of other people's credentials:
a breach, a log line or a bad deploy leaks them all. A key that only passes through the
backend on each call is not stored, but the backend still sees it, and a proxy or log on the
way can still keep it. The only way the site never holds the key is that it never receives it.

Three facts make that possible:

1. **The call can be split.** `IntentService.prepare` does three things in order:
   - it builds the shortlist of candidate players (`_shortlist`);
   - it calls the provider with a fixed system prompt and a strict JSON schema;
   - it validates the reply against the shortlist and the request (`_validate_result`).

   Only the middle step needs the key. The shortlist is deterministic for a given request, so
   the validation can be run again later without stored state.
2. **The major providers accept calls from a browser.**
   - OpenAI's API answers cross-origin requests.
   - Anthropic's Messages API does so when the request carries
     `anthropic-dangerous-direct-browser-access: true`.
   - Google's Generative Language API accepts a browser call with the key in a header.
   - OpenRouter and local servers (Ollama, LM Studio) can be reached the same way, the local
     ones once their own CORS setting allows the site's origin.

   Each of these must be confirmed by the spike in step 1 below before it is offered.
3. **The browser can hold a secret it cannot export.** WebCrypto can create an AES-GCM key
   with `extractable: false` and keep it in IndexedDB. The page can encrypt and decrypt with
   that key, but no script can read its bytes. Only the encrypted API key is stored beside it.

## Decision

1. **The model call moves to the member's browser when the member brings a key.** The backend
   keeps the parts that need no key:
   - `POST /api/v1/llmopt/prompt` takes today's intent request and returns the provider-neutral
     call: the system prompt, the user message (the context JSON with the shortlist) and the
     result schema. The backend calls no model on this route.
   - `POST /api/v1/llmopt/check` takes the same request and the model's raw reply. It rebuilds
     the shortlist deterministically, runs `_validate_result`, and returns the validated draft
     or a refusal.

   The prompt, the schema and the validation stay in one Python source of truth. The solver
   still re-validates every preference it receives, as it does today.
2. **The browser talks to the provider directly.** A small adapter per provider family turns
   the neutral call into that provider's request and reads its reply:
   - OpenAI-compatible chat completions with `response_format: json_schema`, which covers
     OpenAI, Gemini's OpenAI endpoint, OpenRouter and local servers;
   - Anthropic Messages with one forced tool whose input schema is the result schema;
   - Gemini `generateContent` with `responseSchema`, if the OpenAI-compatible endpoint is not
     enough.

   The request goes from the browser to the provider's own host. The key is never in any
   request to the site's origins.
3. **Where the key lives.** The member chooses one of two places:
   - **This visit only (the default).** The key is held in memory and is gone when the tab
     closes.
   - **This device.** The key is encrypted with AES-GCM under a non-extractable WebCrypto key.
     Both the WebCrypto key and the ciphertext are kept in the site's IndexedDB.

   Further rules:
   - Forget erases both at once.
   - The key is never written to `localStorage`, `sessionStorage`, the address, the usage
     record or an error report.
   - A stored key is only decrypted when a request is sent.
4. **The page is closed to scripts that could read the key.** A key in the page is only as
   safe as the page's scripts, so the site adds a Content-Security-Policy (`web/public/_headers`
   has none today):
   - `script-src 'self'`, with no inline script and no third-party script;
   - `connect-src` limited to the site's own origins, the FPL forwarder, the backend, the usage
     Worker and the listed provider hosts, plus `http://localhost:*` and `http://127.0.0.1:*`
     for local models;
   - `object-src 'none'`, `base-uri 'none'` and `frame-ancestors 'none'`.

   A provider outside the list is added by a reviewed change, not by a member typing a URL.
   That way a hostile page state cannot send the key anywhere. The policy is tested against
   the built site before it ships.
5. **The site's own key stays as an option, not the default path.** While the owner keeps
   `SQUADOPT_LLMOPT_API_KEY` set, a member without a key can still use LLMOPT under today's
   limits. With the variable unset, LLMOPT asks for the member's key. Calls made with a
   member's key do not count against the site's 250-a-day budget. `/prompt` and `/check` keep
   a per-visitor rate limit of their own.
6. **What the site can still see.** The member's text and the shortlist pass through `/prompt`
   and `/check`, as today, but they are not logged. The provider's reply passes through
   `/check`. The privacy page names the member's chosen provider as the processor of LLMOPT
   text when a member's key is used.

## Options rejected

- **The site stores keys, encrypted, in its database.** The site would hold every member's
  credential and be the one place to steal them from. A "we never see it" promise would not
  hold.
- **The backend relays the call with the key in the request.** Nothing is stored, but the key
  reaches the site's server, its proxy and any log on the way, every time. It also needs the
  same trust as storing it.
- **Port the prompt and validation to TypeScript.** This removes `/prompt` and `/check`, but it
  leaves two copies of the prompt, the schema and the validator that can drift. Server-side
  validation would also be gone, and the solver's own checks would be the only guard.
- **A member-supplied base URL for any provider.** This needs `connect-src https:`, which lets
  any script that reaches the page send the key anywhere. Local servers are the one exception,
  on loopback addresses only.

## Consequences

- The site never receives a member's key, so a breach of the site or its logs cannot leak one.
- A key in the browser is exposed to a script running in the site's origin. The CSP, the
  absence of third-party scripts and the non-extractable wrapping key narrow that exposure,
  but cannot remove it. The page says the key is kept on this device, and nothing more.
- Members pay their own provider and are limited only by their own quota. The site's model
  bill and its 250-a-day cap stop growing with use.
- The intent request gains two routes and loses nothing. The provider adapters and the key
  store are new web code with their own tests, and the CSP is a new release gate.
- A new provider costs one adapter, one host in `connect-src` and one row in the test matrix.

## Implementation order

Each step is its own PR, reviewed before it is enqueued:

1. **Spike.** From the built site's origin, call each listed provider from a browser with a
   test key: OpenAI, Anthropic, Gemini, OpenRouter and Ollama. Record which ones answer
   cross-origin, and with which headers. Only those go in the list.
2. **Backend.** Add `/prompt` and `/check` with the shared prompt, schema and validator, plus
   unit tests showing that `/check` gives the same verdict as `prepare` for the same reply.
3. **CSP.** Add the CSP to `_headers` with an end-to-end test that loads every page under it.
4. **Web.** Add the key store (memory and device, with Forget) and the provider adapters.
   LLMOPT uses them when a key is present, and today's `/intent` route when it is not.
5. **Text.** Add the privacy page line and a key form with no explanatory text beyond the
   field names, per the site's no-clutter rule.
