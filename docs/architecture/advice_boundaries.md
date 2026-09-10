# Advice transport boundaries

`application.advice_capabilities` owns the supported request combinations. The producer
and API reader use that same selection rule: pure points supports windows 1, 3 and 5;
the wired rival strategies support window 1 and need a different league member as rival.
GET and POST reject unsupported combinations before enqueueing. The rules do not imply
that every supported window can be solved from every captured calendar.

Both cache paths validate `advice_read_v1` before returning the stored bytes. The schema
checks nested moves, players, lineups, multi-week plans and optional pricing fields;
non-finite JSON numbers are refused, including exponent overflow. It keeps legacy optional
fields optional and permits additive payload fields. Existing published advice bytes are
not rewritten. Corrupt job records are an unavailable queue, not an absent job.

Readiness parses the membership directory and checks its identities; existence alone is
insufficient. This is an integrity check, not an age or freshness policy. A missing league
remains a disconnected league; an unreadable publication is reported as not ready.

The browser checks nested advice before rendering and verifies the selected league,
member, strategy, window and supplied week/rival context. Its published index checks
the shape and per-rival addresses. `data/request.ts` bounds fetch and response decoding
with a 15-second default, overrideable through `RequestOptions`. Cancelling a request
aborts its transport and does not start static fallback. Reset, unmount and replacement
cancel the compute flow. The existing five-minute wait is now a wall-clock bound, including
network time; a late response cannot replace a timed-out result. These are UI wait limits,
not worker solve limits, input freshness rules or evidence of server-side job cancellation.

The offline acceptance in `tests/integration/test_publication_contract.py` creates a
synthetic publication with the real Python builder, validates it in Python and passes it
to the real TypeScript advice consumer. It checks file identities and index addresses.
Enable it with `SQUADOPT_PUBLICATION_CONTRACT=1`; Node and `web/node_modules` are required.
CI's web job also runs `SQUADOPT_BROWSER_SMOKE=1` against independent local API and worker
processes and retains failure evidence. Neither check accesses live member data or claims
acceptance of a remote shared filesystem.
