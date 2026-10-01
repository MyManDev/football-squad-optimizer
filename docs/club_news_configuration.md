# Private club-news model settings

The news acquisition command can read a private TOML file. Model calls run on the
acquisition host before the FPL decision capture. The advice backend reads the resulting
artifacts; it does not receive browser keys or make an extra model call for each plan.

Install the existing optional dependency group with
`python -m pip install -c constraints.txt -e ".[llm]"`. Copy
`deploy/club-news.settings.example.toml` outside Git and `web/public`.
Set the provider and the exact model offered by your account. Either reference an existing
server secret with `api_key_env`, or remove that setting and enter `api_key` in the private
copy. Do not pass a key on the command line. Do not commit the private copy.

Check the local settings without fetching pages, contacting a model, reading a roster,
or writing a capture:

```text
python -m scripts.capture_club_news --settings-file <private-file> --check-config
```

This checks syntax, provider-specific settings, a configured key and installed dependencies.
It reports only provider/model and key presence. It cannot verify authentication, available
credit, model access or an endpoint's actual protocol without contacting that service.

For the intended acquisition, using an earlier roster already on the publishing host:

```text
python -m scripts.capture_club_news --settings-file <private-file> --roster-snapshot <capture>
```

The existing `--dry-run` fetches pages and calls the model but writes no capture; it is
different from `--check-config`. Feed the resulting news capture into the normal weekly
flow with `--rotation --rotation-capture <news-capture>`. The news must precede the
decision capture; a new model selection does not rewrite earlier captures.

The environment-only configuration remains supported. `SQUADOPT_LLM_PROVIDER`,
`SQUADOPT_LLM_MODEL` and `SQUADOPT_LLM_API_KEY` override matching file defaults.
OpenAI settings also accept `SQUADOPT_LLM_BASE_URL`, `SQUADOPT_LLM_RESPONSE_FORMAT`,
`SQUADOPT_LLM_MAX_COMPLETION_TOKENS` and `SQUADOPT_LLM_ALLOW_LOCAL_HTTP`.
A provider or endpoint override discards the file-bound model and credential; supply the new
destination's model and key explicitly. A missing named `api_key_env` refuses rather than
trying another credential.

`openai` uses the official endpoint and requires an explicit model; its vendor-key
fallback is `OPENAI_API_KEY`. `openai-compatible` requires an explicit model and
`base_url`, with a generic key or explicitly named private secret. It has no automatic
OpenAI-key fallback. Remote endpoints require HTTPS. Local HTTP needs an explicit opt-in
and the adapter's loopback restriction.

Strict `json_schema` output is the default. Select `json_object` explicitly only for a
compatible service that does not support it; local claim/schema validation still applies.
The completion token limit is a positive integer no greater than 16000.
There is no automatic provider, model or output-format fallback.

Anthropic and Gemini continue to work through the same settings. Their existing defaults
remain unchanged. Gemini's supported-model/thinking-setting list remains in force; this
change does not claim that an arbitrary new Gemini model is compatible.

API readiness is separate from club coverage. The committed source registry contains
three real hosts, for Liverpool, Newcastle and Crystal Palace, plus an Example FC
placeholder. Palace is limited to the credited, linked written-article scope recorded in
[the source reading](club_news_sources.md). Entering a key does not supply news for the
entire captured league. The existing `--registry` option accepts an operator-maintained
source file; the same terms-reading and bounded-discovery rules apply.


## Bounded provider verification

Limit a first paid or quota-limited call to one exact registered club. Selection is checked
before fetching pages or contacting the provider; a misspelled name refuses the run.
Repeated selections do not repeat requests. All registered pages for the selected club
remain in scope.

```text
python -m scripts.capture_club_news --settings-file <private-file> --roster-snapshot <capture> --club Liverpool --capture-root <trial-output>
```

Repeat `--club` to select more clubs. `--capture-root` changes only where new news is
written; the roster is still read from `--snapshot-root`. Without these options the
existing registry and output defaults are unchanged. The command reports roster clubs,
registered and selected clubs, received documents, coded responses and missing coverage
separately. A coded empty response is a successful response, not a player update or proof
that no news was published. The reader samples the registered pages and at most ten linked
articles per host; it does not claim exhaustive coverage.

A private Gemini file can use `provider = "gemini"`, a supported `model` such as
`gemini-3.6-flash`, and the existing `api_key_env` or `api_key` setting. A transient service
failure is recorded as a failed call. There is no automatic second request or silent model
change. Validate a saved response against its captured source spans before claiming that
it supplied any usable statements. The source reader and downstream timing checks apply
regardless of provider.

## Fixture components for minute evidence

The v1 builder can publish the forecast and its fixture components from the same fit:

```text
python -m scripts.build_football_forecast --snapshot-root <captures> --snapshot-id <capture> --archive-root <authorized-archive> --artifact-root <artifacts> --with-components
```

This is opt-in and v1-only. The companion is validated against the full five-week forecast,
its captured calendar and availability before either new document is published. Existing
conflicting files are refused, not replaced. The companion is written first; an interrupted
identical run can complete the forecast. The two-file publication is not a transaction. A
per-capture publication marker excludes a second cooperating writer; after a process is
killed an operator must inspect that marker before removing it.

This command still fits the producer's configured archive seasons, including 2025-26.
`--with-components` does not authorize archive access or manufacture a missing basis for an
old forecast. Where a season is held out or its access is restricted, do not run this command
against it. Old weekly totals alone cannot recover the exact player-fixture components.
New news must precede the decision capture; changing its date to fit an old capture is not
an integration path.

## Personal ChatGPT and Claude accounts

API configuration is not a subscription-account connection. As checked on 2026-10-01,
[Sign in with ChatGPT for websites](https://developers.openai.com/siwc/website) requires
provider acceptance for the website trial; identity login alone does not grant model use.
The [open-source token-sharing flow](https://developers.openai.com/siwc/token-sharing-open-source)
is for locally hosted applications. It is not a substitute for acceptance of this hosted
site. The [provider interest form](https://openai.com/form/sign-in-with-chatgpt-interest/)
is the route for a hosted integration.

[Claude Code's official usage policy](https://code.claude.com/docs/en/legal-and-compliance)
distinguishes native end-user Claude Code use from a third-party application routing
Claude.ai subscription credentials. This site does not collect subscription session tokens
or advertise a working account connection. Provider-approved hosted integration remains a
separate prerequisite; the operator's Gemini/API configuration does not resolve it.
