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

API readiness is separate from club coverage. The committed source registry currently
contains real hosts for Liverpool and Newcastle, plus an Example FC placeholder; entering
a key does not supply news for all twenty clubs. The existing `--registry` option accepts
an operator-maintained source file. This package does not extend or replace that registry.
