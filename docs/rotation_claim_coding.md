# Rotation claim coding: the frozen question, and the citation the model cannot write

A5 built the rotation lane behind a stub and left one method unimplemented:
`ClubNewsProvider.code`, the step that asks a model what a club's announcement says about who
will start. This is that step. It changes nothing else — every test downstream of it still
runs offline, because none of them go through it.

Two files:

| File | What it is |
| --- | --- |
| `src/squadopt/data/sources/club_news_coding.py` | The frozen prompt, the response schema, and the deterministic locator. No network, no SDK. |
| `src/squadopt/data/sources/club_news_anthropic.py` | The one place in the repository that calls a model. |

## The problem this is shaped around

A5's parser reads a claim carrying **byte offsets** into the fetched document, and
`resolve_span` re-reads those offsets at render time to show a member the club's own words.
That is the right shape for a citation and the wrong thing to ask a model for. A span is
arithmetic over UTF-8 bytes; an off-by-forty span still lands *inside* the document, so
`resolve_span` would check the digest, find it correct, and hand a member a sentence about a
different player. A digest's worth of confidence behind the wrong words is worse than no
citation at all.

So the model is never asked to count. It is asked for the sentence, verbatim, and this
repository finds it.

## Two formats

`rotation_claim_coding_v1` is what the prompt asks for. `rotation_claim_response_v1` is what
the parser reads. They differ in exactly one field per claim:

| `rotation_claim_coding_v1` | `rotation_claim_response_v1` |
| --- | --- |
| `quote` — a span of the document, copied character for character | `span_start`, `span_end` — byte offsets into the same document |

Everything else — `player_name`, `team_name`, `disposition`, `speaker`, `source_url`,
`paraphrase`, and the per-document dateline block — is identical.

`locate_claim_response` turns the first into the second by searching the fetched bytes for the
quote. **Exactly one occurrence is required.** Zero means the model did not copy the document
— it tidied a dash, dropped a comma, or wrote the sentence it remembered — and a claim whose
citation cannot be found is not weakened, it is unfounded. More than one means the offsets
would be a coin toss between two places in the page.

The locator is pure and offline. Same response, same documents, same output bytes, same
digest. That is the property the whole lane rests on, and it is why the model's own text is
stored unparsed as its own payload: asking a model twice does not reproduce anything.

The locator does **not** check the claims. The dateline pairing, the closed vocabularies, the
duplicate-player refusal and the span bounds all belong to `parse_claim_response`, which owns
them for every response however it arrived.

## The disposition vocabulary, minus one

The prompt asks for seven of the eight dispositions. `not_addressed` is excluded, and the
prompt says so explicitly rather than leaving the closed list looking complete: a model only
ever sees the documents it was handed, so it cannot distinguish "nobody wrote about him" from
"his club was never read". The pipeline computes that absence from the roster and the coverage
lists. Asking a model for it would be asking it to report a silence it is not in a position to
hear.

The schema's enumerations are **generated** from the same tuples the parser validates against.
Two copies of a closed vocabulary is one copy too many: a disposition added to the tuple and
forgotten in a hand-written schema would come back as a refused week — the model answering
correctly and the request rejecting it — which is a hard failure to read.

## The instrument is frozen, and fingerprinted

`coding_prompt_sha256()` digests the contract version, the model identifier, the effort, the
prompt text and the response schema, canonically. Today:

```
e755c70b96cef2dda4523d04e46292913bf3f8638d6b39261ee4ebd144ffbf5d
```

That value is pinned in `tests/unit/test_club_news_coding.py`. Editing the prompt changes it
and fails the test, which is the reminder to bump `ROTATION_CLAIM_CODING_CONTRACT_VERSION`
deliberately: a response coded under the old wording is not comparable with one coded under
the new.

It is a digest of the **instrument**, not of the **sample**. Which documents and which roster
went in is fingerprinted elsewhere and already in the manifest (`document_sha256s`,
`roster_snapshot_id`). Mixing the two would mean a week's prompt digest changed because a club
published a longer page, which tells a reader nothing about whether the question changed.

`effort` is sent explicitly for the same reason the prompt is a constant: an instrument whose
settings can be changed underneath it is not frozen.

## What the request deliberately does not do

- **No tools.** No web search, no fetch, no code execution. The request carries no `tools` key
  at all. A model that could fetch the page itself would make the manifest's document digests
  a fiction: the bytes we hashed would no longer be the bytes it read. This is enforced
  structurally and asserted in `test_the_request_attaches_no_tool_of_any_kind`.
- **No fallback model.** A policy decline is recorded as a refusal, not re-run elsewhere.
  Quietly retrying the week on a second model would make one week's claims a mixture while the
  manifest names a single model.
- **No credential guessing.** The SDK resolves a key, an auth token or a saved login profile on
  its own. This reads one named variable and passes it explicitly, because which credential
  answered is part of a week's provenance.
- **No retry on a refused response.** A response the parser rejects is a finding, not a
  transport failure. Asking again until the answer parses is how a pipeline starts selecting
  its own evidence. Transport retries (connection errors, 429, 5xx) are the SDK's and are
  bounded at four.
- **No prompt caching.** One call per club per week is not a cache-hit pattern worth a
  request-shape change, and the shape has to be replayable byte for byte.
- **No streaming.** A club's page plus a squad list is a few thousand input tokens and its
  claims a few thousand out. Neither end is long, 16 000 output tokens is the documented
  ceiling below which one request will not hit an HTTP timeout, and one unstreamed request is a
  simpler shape to freeze.

Four states are refused on the reading side, because each one must not become "the model
produced no disposition for these players" — a sentence this pipeline publishes, which has to
be true when it appears: a declined request, a response truncated at the output ceiling, a
response with no text at all, and a response that does not name the model that produced it.
The empty answer has a shape, and it is a document with an empty `claims` array.

## Running it

The SDK is an optional install and the key comes from the environment.

```bash
python -m pip install -c constraints.txt -e ".[llm]"    # or ".[api,dev]", which includes it
export ANTHROPIC_API_KEY=...                            # PowerShell: $env:ANTHROPIC_API_KEY = "..."
```

`anthropic` is declared in the `llm` extra and in `dev`. The second is not redundant:
`mypy --strict src` is a gate, and a gate that cannot see the library it is checking is not
checking it. It is **not** in the runtime dependencies and not in `api`, so a research-only
install and the deployed image both stay free of it — the backend answers from stored
artifacts and never asks a model anything.

Without a key the lane still runs end to end on `FixtureClubNewsProvider`, and the missing-key
refusal says so.

## Replaying a week with the network unplugged

1. Read the stored coding response and the stored documents from the snapshot store.
2. `locate_claim_response(response, documents)` — pure, deterministic.
3. `parse_claim_response(located, documents)` — the same claims, the same digests, the same
   spans.

Step 1 is the only step that ever touched a network, and it happened once. Nothing after it
asks a model anything.

## Fixtures

`data/sample/club_news_coding_v1.fixture.json` is **derived** from
`data/sample/club_news_v1.fixture.json` by `scripts/generate_club_news_coding_fixture.py`:
every quote in it is cut out of the located fixture's own document bytes at the offsets that
file already declares. Locating it therefore has to reproduce the claims the located fixture
carries, offsets included, and neither half was fitted to the other by hand. It also carries
the five responses the locator must refuse — a quote the model tidied, a fragment that matches
twice, a page that was never fetched, a version bump, a missing field — beside the good one,
because "the shape the locator does not accept" is a property of the format and a copy of it
inside a test file would drift away from the format it is meant to violate.

Nothing under `data/sample/` is any club's captured bytes. Real captures stay under
`data/snapshots/`, which is gitignored.

## Open for review

- **Provenance is now per club; the exporter's call granularity is not.** `ModelProvenance` is
  the per-club record and `ClubModelProvenance` collects one per club, so a row's
  `model_response_sha256` is the digest of that player's club's response and the manifest lists
  every response the week holds. What has not moved is how many calls the exporter makes: it
  still asks once, because splitting the request per club needs documents that know their own
  club and a `RawDocument` does not carry one until the fetch adapter that assigns it exists.
  `code(documents, roster)` is already club-agnostic, so that adapter changes the caller and
  nothing here.
- **The runbook does not yet mention the key.** `docs/weekly_runbook.md` is shared, so the
  operator-facing note about `ANTHROPIC_API_KEY` and the `llm` extra is left for whoever owns
  that page rather than added unilaterally.
