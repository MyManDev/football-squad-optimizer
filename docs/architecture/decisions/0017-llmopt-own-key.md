# ADR 0017: LLMOPT with the member's own model key, which the site never receives

- **Status:** accepted by the owner on 2026-11-17 ("herkes kendi api keyini girecek sonra
  silinecek api keyleri": every member enters their own key, and keys are deleted afterwards).
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

The owner's direction on 2026-11-17: every member enters their own API key for their own
model; the site never holds the keys, and a key is deleted afterwards.

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

   Measured on 2026-11-17 with requests carrying `Origin: https://squadopt.mymandev.com`:
   OpenAI, Anthropic, Gemini (OpenAI-compatible and native), OpenRouter, Mistral, Groq and
   DeepSeek all answer the preflight for the headers they need. Each also returns its 401 or
   400 for an invalid key with `Access-Control-Allow-Origin`, so the page can tell the member
   that the key was refused. Local servers are not measured; their CORS is the member's
   setting.
3. **A key needs no storage at all.** The page can keep it in a variable for as long as the
   tab is open. Nothing is written to `localStorage`, `sessionStorage`, IndexedDB, a cookie or
   the disk, so closing the tab deletes it.

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
3. **Where the key lives: in memory, for this tab, and nowhere else.** The member pastes the
   key into a password field. The page holds it in a module variable that no other module
   reads, and puts it only in the `Authorization` (or `x-api-key`, `x-goog-api-key`) header
   of the request to the provider's host. It is deleted:
   - when the tab is closed or reloaded;
   - when the member presses Delete;
   - after 30 minutes without a request.

   It is never written to `localStorage`, `sessionStorage`, IndexedDB, a cookie, the address,
   the saved LLMOPT session, the usage record or an error report. The field is a text field
   drawn as dots, with `autocomplete="off"`: a browser offers to save what a password field
   held once the field leaves the page, whatever `autocomplete` says, and a saved key would
   outlive the tab. Leaving the LLMOPT page inside the site deletes the key as well, and the
   30 minutes are read from the clock, so a tab that slept past them drops the key when it
   is next used or looked at.
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
5. **Every member brings a key.** LLMOPT asks for the member's provider and key before the
   first message: the chat is off until a key is held, and the rules can be edited by hand
   meanwhile. The site's own key (`SQUADOPT_LLMOPT_API_KEY`) was a fallback during the
   change and is unset since 17 November 2026; the page no longer calls `/intent`. `/prompt`
   and `/check` keep a per-visitor rate limit of their own.
6. **What the site can still see.** The member's text and the shortlist pass through `/prompt`
   and `/check`, as today, but they are not logged. The provider's reply passes through
   `/check`. The privacy page names the member's chosen provider as the processor of LLMOPT
   text when a member's key is used.

## Options rejected

- **The key kept on the device, encrypted under a non-extractable WebCrypto key.** It saves a
  paste, but a key that outlives the tab contradicts the owner's direction that keys are
  deleted afterwards, and it widens the window in which a hostile script could use it.
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
- While the tab is open, the key is exposed to a script running in the site's origin. The
  CSP and the absence of third-party scripts narrow that exposure, but cannot remove it.
  Closing the tab removes it entirely.
- The member pastes the key again in every new tab.
- Members pay their own provider and are limited only by their own quota. The site's model
  bill and its 250-a-day cap stop growing with use.
- The intent request gains two routes and loses nothing. The provider adapters and the key
  store are new web code with their own tests, and the CSP is a new release gate.
- A new provider costs one adapter, one host in `connect-src` and one row in the test matrix.

## Implementation order

Each step is its own PR, reviewed before it is enqueued:

1. **Spike (done 2026-11-17).** Preflight and invalid-key responses measured for eight hosts;
   all eight answer cross-origin. A call with a real key per provider is the first test of
   step 4.
2. **Backend.** Add `/prompt` and `/check` with the shared prompt, schema and validator, plus
   unit tests showing that `/check` gives the same verdict as `prepare` for the same reply.
3. **CSP.** Add the CSP to `_headers` with an end-to-end test that loads every page under it.
4. **Web.** Add the in-memory key holder (with Delete and the idle timeout) and the provider
   adapters.
   LLMOPT uses them when a key is present, and today's `/intent` route when it is not.
   (Since step 6 the page uses only the member's key.)
5. **Text.** Add the privacy page line and a key form with no explanatory text beyond the
   field names, per the site's no-clutter rule.
6. **Own key only (2026-11-17).** The site's key is unset and the page reads the chat only
   with the member's key. The form gains its title and one line that says what turns the
   chat on, since a chat that is off needs that much said. A chat-completions provider is
   given room to think (8192 reply tokens), because a reasoning model counts its thinking
   against the limit and the answer's own 1200 stopped such a model before it wrote.
7. **No model code in the backend (2026-11-18).** `/intent`, its provider, the daily budget
   and the `SQUADOPT_LLMOPT_*` settings are removed. `llmopt_intent.py` keeps the prompt,
   the schema, the shortlist and the validator, which `/prompt` and `/check` use. The
   Context above describes the backend as it was when this was decided.
