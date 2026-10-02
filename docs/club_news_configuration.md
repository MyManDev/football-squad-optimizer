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
There is no command-line option for the provider, the model, the endpoint or the key.

Where each setting comes from, first match wins:

| Setting | 1 | 2 | 3 |
| --- | --- | --- | --- |
| Provider | `SQUADOPT_LLM_PROVIDER` | the file's `provider` (required in a file) | `anthropic` when there is no file |
| Model | `SQUADOPT_LLM_MODEL` | the file's `model`, if the destination is the file's | the default of `anthropic` or `gemini`; any other provider refuses |
| Endpoint | `SQUADOPT_LLM_BASE_URL` | the file's `base_url`, if the provider is the file's | the official address for `openai`; `openai-compatible` refuses without one |
| Key | `SQUADOPT_LLM_API_KEY` | the file's `api_key_env` or `api_key`, if the destination is the file's | the provider's own variable (`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`) |

The destination is the provider together with its endpoint. An environment override that
names a different destination leaves everything the file bound to its own destination
behind: the model, the key, the response format, the token limit and the local-HTTP
permission. The new destination then needs its own model and key, from the environment or
from the provider's default and own key variable where it has them. A missing named
`api_key_env` refuses rather than trying another credential.

`--check-config` prints the provider and model it resolved and, for the OpenAI adapters,
the response format and token limit that will be requested.

`openai` uses the official endpoint and requires an explicit model; its vendor-key
fallback is `OPENAI_API_KEY`. `openai-compatible` requires an explicit model and
`base_url`, with a generic key or explicitly named private secret. It has no automatic
OpenAI-key fallback. Remote endpoints require HTTPS. Local HTTP needs an explicit opt-in
and the adapter's loopback restriction.

Strict `json_schema` output is the default. Select `json_object` explicitly only for a
compatible service that does not support it; local claim/schema validation still applies.
The completion token limit is a positive integer no greater than 16000.
There is no automatic provider, model or output-format fallback.

Anthropic and Gemini continue to work through the same settings and model defaults.
Configured acquisition providers do not retry automatically, so the request budget also
bounds transport attempts. Direct Anthropic adapter callers retain their existing retry
default. Gemini's supported-model/thinking-setting list remains in force; this change does
not claim that an arbitrary new Gemini model is compatible.

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
python -m scripts.capture_club_news --settings-file <private-file> --roster-snapshot <capture> --club Liverpool --capture-root <trial-output> --max-model-calls 1
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

## Which instant the coding observes from

One acquisition run keeps four times apart, because each answers a different question:

| Time | What it is | Where it comes from |
| --- | --- | --- |
| Publication | when the club says an article was published | the held page's own verifiable fields; never rewritten |
| Fetch | when one page was read | recorded on each document |
| Coding observation | the one instant the week's coding looks from | taken once, after the last page was read |
| Capture completion | when the capture was written | after coding |

The run's own start settles the target gameweek and deadline before any page is read. It
also bounds the inputs that must already exist: an earlier news capture given for reuse has
to precede it.

The coding observation is what the document selection, the model's decision context
(`as_of`) and the target-deadline check all use. It used to be fixed before the fetch. An
article published while the pages were being read was then turned away as
`publication_after_observation`, although its page was already in hand. Taken after the
fetch, that article is judged against a moment at which it had been read. The time rule
applies only to a publication time the held page states verifiably and to the instant: such
an article is still turned away when it is later than the observation, or more than seven
days older than it. A page that states only a date, or nothing verifiable, is not turned
away on time.

The command prints the instant on its `Observed` line. If the target deadline passed while
the pages were being read, the run stops with `Refused`: nothing is coded against the closed
week, no capture is written, and the next gameweek is not taken instead. Start a new run for
it. The provider settings are still checked before any page is fetched, so a missing key,
an unlisted model or a client library that is not installed refuses with nothing read; the
adapter itself is built after the fetch. A page stamped later than the observation, or an
observation earlier than the run's start, means the clock went backwards, and the run stops
the same way. When no page could be read at all, nothing is observed and no adapter is built.

The documents are selected once, and that one selection is both what is sent for coding and
what the run reports as selected.

Reuse is unchanged, and it is still asked for with `--previous-news-capture`. The
observation is not part of what makes a question the same question. An earlier answer is
reused as it was given, with its own model revision and the source's own publication times,
when everything else is the same: provider, model, prompt, endpoint, output format and token
limit, the season, gameweek and deadline, the roster, and the selected documents with their
bytes and `Last-Modified`. The observation can still change which documents are selected (a
newly eligible article, one that has aged out of the seven days), and a different selection
is a different question. What a later run adds to a reused answer is when it read the pages.

Moving the observation changes which documents are eligible in the narrow case above. It is
not new editorial content, it does not make any statement more reliable, and it is no
evidence about how well stated news predicts who plays.

## Fixture components for minute evidence

The v1 builder can publish the forecast and its fixture components from the same fit.
Choose every permitted training season explicitly. For an archive-only development run
that excludes 2025-26 and the current season:

```text
python -m scripts.build_football_forecast --snapshot-root <captures> --snapshot-id <capture> --archive-root <authorized-archive> --artifact-root <trial-artifacts> --with-components --training-season 2022-23 --training-season 2023-24 --training-season 2024-25
```

Repeat `--training-season` for each allowed season; a comma-separated list is not accepted.
Excluded archive seasons are neither read nor hashed. The forecast and companion record
the selected seasons and actual training populations. Choosing a different population is
a new development fit, not evidence that the resulting model is better. The 2022-23 season
supplies historical priors rather than supervised target rows.

To include 2026-27, add `--training-season 2026-27` only when the selected immutable capture
contains every required settled `event-gwNN-live.json` from gameweek 1 through the week
before its target. A capture containing only bootstrap and fixtures cannot supply those
observations. The builder refuses missing history; do not add files to an existing capture.

This is opt-in and v1-only. The companion is validated against the full forecast horizon,
its captured calendar and availability before either new document is published. Existing
conflicting files are refused, not replaced. The companion is written first; an interrupted
identical run can complete the forecast. The two-file publication is not a transaction. A
per-capture publication marker excludes a second cooperating writer; after a process is
killed an operator must inspect that marker before removing it.

Omitting `--training-season` retains the existing archive population, including 2025-26,
and includes captured current-season history. Do not omit the option when a season is held
out or access is restricted. `--with-components` itself does not authorize archive access
or manufacture a missing basis for an old forecast. The snapshot reader still verifies
every payload in the named capture; the training selection is not a payload filter.

Use a new ignored trial artifact directory for independent validation. Writing a trial
forecast does not activate it for the live service. Old weekly totals alone cannot recover
the exact player-fixture components. New news must precede the decision capture; changing
its date to fit an old capture is not an integration path. Activation requires the normal
publication process for the exact new decision capture and its matching artifacts.

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
