# Observing the one-week opening

Use the same observation interval before and after a setting change. Record the interval, the source of each count and its denominator. Keep only aggregate numbers. Leave an unavailable count blank. The frozen comparison establishes local behavior on twenty member-weeks. It made no provider calls. [Measured workload](llmopt_week_first.md)

| Event | Where the owner can see it | Counting scope |
| --- | --- | --- |
| Budget exhausted | Worker JSON events for a refused solve, or the budget flag on a partial answer | Refused worker attempts can be counted for the retained interval. Device and partial results require an observed run. |
| Model reply rejected | The individual `/api/v1/llmopt/check` response, code `REPLY_REFUSED` | The owner can tally the two-message checks during the provider test. A site-wide counter is unavailable. |
| Device plan routed to the server | The confirmation's initial device selection, final route and actual server submission | A controlled replay can count the change of route. Server logs contain only the final request. |

### Runs that exhaust a budget

In a controlled one-week replay, count one affected confirmation if any of its operations reports `RUN_BUDGET_EXHAUSTED`, or a returned preference bundle or priority result has `budget_exhausted: true`. A partial plan can carry that flag in a successful answer. Inspect the advice POST response code, terminal advice-job error code and device result in memory. A boolean per current confirmation prevents retries, polls and repeated components from increasing the count. Divide by the number of one-week runs confirmed in that replay. A cancellation, a full connection queue and a merely feasible plan have separate meanings. [Admission](../../src/squadopt/platform/advice_runs.py) · [Grouped results](../../src/squadopt/platform/advice_preference_bundle.py) · [Device budget](../../web/src/features/league/device/workBudget.ts)

Existing worker events cover one subset. In an already retained local worker event stream, count records whose `event` is `advice_job_refused`, `code` is `RUN_BUDGET_EXHAUSTED` and `window` is `1`. Count rows in place and retain only the total. A row represents a refused worker attempt with a known window. Admission can return HTTP 409 before a worker starts, and the browser can exhaust its own budget. The worker metric `advice_jobs_total{outcome="refused"}` combines refusal reasons and windows. The API's `advice_open_job_refused_total` counts the per-connection open-job limit. Neither supplies the affected-run total. [Worker events](../../src/squadopt/platform/advice_queue.py) · [Window field](../../src/squadopt/platform/advice_worker.py) · [HTTP handlers](../../src/squadopt/api/app.py)

For the owner’s observation on the live host, use the `squad_compose` function in the [opening procedure](llmopt_one_week_opening.md). Supply the start and end of the observation in UTC. This command prints one integer from the current worker container. Take the count before recreating that container if the interval will be needed later. If the interval falls outside available log retention, record it as unavailable.

```sh
squad_compose logs --no-color --no-log-prefix --since "$start_utc" --until "$end_utc" worker |
  python3 -c '
import json, sys
count = 0
for line in sys.stdin:
    try:
        event = json.loads(line)
    except ValueError:
        continue
    if isinstance(event, dict) and event.get("event") == "advice_job_refused" and event.get("code") == "RUN_BUDGET_EXHAUSTED" and event.get("window") == 1:
        count += 1
print(count)
'
```

### Model replies rejected by the checker

For a known one-week sample, count completed `POST /api/v1/llmopt/check` responses with HTTP 422 and `error.code == "REPLY_REFUSED"`. Count each response once. To report a share of replies validated, divide by successful checks plus `REPLY_REFUSED` and `PLAN_DATA_CHANGED` checks. Keep the stale-plan outcome separate. A malformed check request yields `VALIDATION_FAILED`. Credential, rate-limit and provider failures are separate outcomes. A clarification can pass validation. The checker exports no counter for this distinction. The API's `advice_rejected_total` counts specific advice lookup errors. HTTP status alone cannot identify a rejected model reply or its draft window. A local fixture can tally the response code without storing either body or contacting a provider. [Checker branches](../../src/squadopt/api/llmopt.py) · [Keyless fixtures](../../tests/unit/test_llmopt_keyless_routes.py) · [Browser submission](../../web/src/features/league/llmopt/intentSource.ts)

### Device plans routed to the server

Use fresh one-week confirmations for which the planner initially selected a device run as the denominator. This requires a current matching master grant and a consistent published member block. The member, capture, held squad, bank and known free transfers must agree. The planner checks that the requested stages support the plain one-week pure-points route. Unsupported rules or chip combinations, an unverifiable device table or an unavailable local capacity receipt can change the prepared route to the server before any worker starts. [Confirmation](../../web/src/features/league/llmopt/releaseRun.ts) · [Supported selections](../../web/src/features/league/device/selection.ts) · [Input and receipt checks](../../web/src/features/league/device/adviceClient.ts)

Count a fallback once when the planner first selects the device, prepares the base request for the server and actually submits it over the remote transport. A warm HTTP 200 can complete that sequence without opening a job. A controlled local confirmation can record these three booleans in memory and use its known fixture to distinguish missing inputs from unavailable storage. A browser worker that already started remains a separate outcome. Aggregate API jobs and cache hits lack the initial device decision. [Routing fixture](../../web/src/features/league/llmopt/deviceRoute.test.ts) · [Exported advice counters](../../src/squadopt/platform/advice_observability.py)

### Privacy and coverage

The current exports cannot reconstruct the three one-week rates across users. An owner who needs those rates must separately approve aggregate instrumentation at the decision points above.

Keep the aggregate observation separate from the tab's application state. To resume a clarification, the page saves the member's preceding message and the question in the plan session. The session can persist in `sessionStorage`, or in browser history state when storage fails and the confirmation has a run ID. Leave both in the tab. Keep only the counts and their coverage in the operator note. Exclude identifiers, message or key material, headers and bodies. Do not export browser storage, a HAR, traces or raw log lines. [Clarification handling](../../web/src/features/league/llmopt/LLMOptPage.tsx) · [Session persistence](../../web/src/features/league/llmopt/planSession.ts)
