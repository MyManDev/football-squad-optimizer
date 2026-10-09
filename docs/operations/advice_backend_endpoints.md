# Advice backend endpoints and what replaces each

Route 1 of #988 retires the advice backend for the device path, in small pull requests
after the GW6 publish. The route was recorded on #632 (comment 6033468399, 2026-10-07).
Its first step is this inventory: every route the backend serves, who calls it, what the
site does when it is built without `VITE_ADVICE_API_ORIGIN`, and what replaces the route.

Everything below was read at develop 6e7e6176, and line numbers refer to that commit.

#1001 owns three parts of the replacement: preferences on the device, hiding Contribute
without an origin, and keeping the weekly football build. This page links #1001 and does
not restate its steps.

## Where the code is

- The API is `src/squadopt/api/app.py` (`app.py` below) and the contributions router in
  `src/squadopt/api/contributions.py` (`contributions.py` below). The deployment's
  composition always mounts the router (`src/squadopt/api/runtime.py:114`).
- The site reads `VITE_ADVICE_API_ORIGIN` in three places: `createAdviceClient`
  (`adviceClient.ts:476-483`), `ContributePage.tsx:23` and `DecisionPreferencesPanel.tsx:43`.
  CI passes `vars.ADVICE_API_ORIGIN` to the site build and to the e2e run
  (`.github/workflows/ci.yml:196` and `:222`).
- Short names: `adviceClient.ts`, `useAdviceJob.ts`, `adviceSelection.ts`,
  `DecisionPreferencesPanel.tsx`, `ModelComparison.tsx` and `OfficialInformationCard.tsx`
  are in `web/src/features/league/advice/`. `useLeagueMemberData.ts`,
  `useMemberAdviceView.ts` and `LeagueMemberView.tsx` are in
  `web/src/features/league/pages/`. `selection.ts` is in `web/src/features/league/device/`.
  `ContributePage.tsx` is in `web/src/features/contributions/`.

With an empty origin, `createAdviceClient` returns the static client
(`adviceClient.ts:120-171`). It has no capabilities read, so the member page is the
published tree plus the device's one-week plan.

## The routes the site calls

The API declares 18 routes. The site calls 7 of them.

| Route | What it does | Called from | Built without an origin | Replaced by | Lost until then |
| --- | --- | --- | --- | --- | --- |
| `GET /api/v1/leagues/{league_id}/capabilities` (`app.py:454`) | Says what the service computes now for the league: strategies and windows, Top 100 weights, the manager's word, preferences, models, chip windows, held chips and the football decision information (`src/squadopt/platform/advice_read.py:477-533`). | `useLeagueMemberData.ts:52-60`, once per member page. | Not called. The static client has no capabilities read, so the query is disabled (`useLeagueMemberData.ts:54-59`) and the page treats the service as absent (`:70-77`). The controls come from the published index and the device's statement (`adviceSelection.ts:393-401`). | The published advice index and the device's statement. #981 step 5 makes the page device-first. | Nothing by itself. What it switched on is in the POST row and in the section below. |
| `GET /api/v1/leagues/{league_id}/entries/{entry_id}/advice` (`app.py:465`) | Reads an answer the service already computed. It never computes. | `useAdviceJob.ts:196` on open, only when the service answered its capabilities (`useMemberAdviceView.ts:116`, `:128`). `useAdviceJob.ts:340` after a job completes. `ModelComparison.tsx:77-82`. | Not called. The static client reads the published document from the tree (`adviceClient.ts:131-155`). | The static tree for what the weekly publish wrote. The device for the one-week selections it takes (`selection.ts:58-65`). | The cache of answers computed on request. |
| `POST /api/v1/leagues/{league_id}/entries/{entry_id}/advice` (`app.py:529`) | Answers from the cache, or queues a CP-SAT job and returns 202 with a job id. | `useAdviceJob.ts:253`, from the compute button and from `ModelComparison.tsx:137`. | Not called. The static client answers from the tree or says unavailable (`adviceClient.ts:157-164`). A selection that neither the tree nor the device takes shows no plan. | The device one-week model on develop: the plain plan, four chips, both rival strategies and the Top 100 weights. Preferences at window one: #1001 steps 1 to 3. 3 and 5 week windows: #984, only if its verdict says device. Other leagues and any entry: #981 and #983. | See "Lost until the device path covers it". |
| `GET /api/v1/advice-jobs/{job_id}` (`app.py:606`) | Polls one queued job. | `useAdviceJob.ts:315`. | Not called, since no job is filed. If the tab still remembers a job id, the static client reports that job as failed without a request (`adviceClient.ts:166-170`). | Nothing is needed. The device solves in a Web Worker inside the page (`web/src/features/league/device/useDevicePlan.ts`). | Nothing beyond the POST row. |
| `GET /api/v1/contributions/players` (`contributions.py:32`) | Serves `players.json` from the site data root: the published roster. | `ContributePage.tsx:102-106`. `DecisionPreferencesPanel.tsx:40-82`, for the avoid list. | The preferences panel does not ask. It is enabled only by `capabilities.preferences` (`LeagueMemberView.tsx:316`), and its effect returns at line 41. The Contribute page still asks, at the site's own host (`ContributePage.tsx:23-28`). The static host serves no JSON there, so the read fails and the page shows its unavailable state (`:172-180`). | Avoid list: the published device table, #1001 step 3. Contribute: hidden without an origin, #1001 step 4 (PR #1022). The same roster is already in the static tree as `data/players.json`, written by `scripts/build_player_catalog.py` and last changed in #779. | The Contribute form. |
| `GET /api/v1/contributions` (`contributions.py:37`) | Returns approved comments for one player, 50 a page. | `ContributePage.tsx:113-119`. | Never reached, because the roster read fails first. | Nothing. #1001 step 4 hides Contribute. | Reading approved comments. |
| `POST /api/v1/contributions` (`contributions.py:51`) | Stores a pending comment in `contributions.sqlite3` under the backend store root (`src/squadopt/api/runtime.py:114`). | `ContributePage.tsx:120-137`. | Never reached. | Nothing. See "Still to decide". | Sending comments. |

## Not called by the site

| Route | Callers | After route 1 |
| --- | --- | --- |
| `GET /api/v1/leagues/{league_id}` (`app.py:445`): connected or not, league name, gameweek and member count (`src/squadopt/platform/advice_read.py:440-461`) | `scripts/smoke_backend_local.py:143` | The site reads the league from the static tree (`web/src/features/league/directory.ts:40`, `web/src/features/league/data.ts:93`). The route goes with the backend. |
| `GET /health` (`app.py:668`) | The uptime workflow (`.github/workflows/backend-uptime.yml:56`), the logon watcher (`scripts/start_backend_at_logon.ps1:321`), `scripts/run_backend_local.ps1:437`, `scripts/backend_status.py:273`, `scripts/smoke_backend_local.py:131`, the container probes (`deploy/compose.yaml:58`, `deploy/containerapp.yaml:124` and `:130`) | The uptime schedule is turned off in its own PR. The other callers go with the backend. |
| `GET /ready` (`app.py:635`) | `backend-uptime.yml:60`, `start_backend_at_logon.ps1:218`, `run_backend_local.ps1:227` and `:456`, `scripts/release/restart_backend.ps1:234`, `backend_status.py:271`, `smoke_backend_local.py:135` | As for `/health`. |
| `GET /metrics` (`app.py:620`) | `backend_status.py:272`, `run_backend_local.ps1:233`, `restart_backend.ps1:160`, the load tool (`src/squadopt/platform/advice_load.py:108`) | Goes with the backend. |
| `GET /api/v1/info` (`app.py:672`) | None | Goes with the backend. |
| `GET /api/v1/seasons` and the five season views under `/api/v1/seasons/{season}/` (`app.py:676-704`) | None | The site already reads the same files from the static tree (`web/src/data/client.ts:95-125`). |

Also outside the site:

- FastAPI's own `/docs`, `/docs/oauth2-redirect`, `/redoc` and `/openapi.json` are on,
  because `create_app` keeps the framework defaults. Nothing calls them.
- With `-WorkerMetricsBasePort` set, each advice worker serves its own `/health` and
  `/metrics` on a loopback port (`src/squadopt/platform/worker_metrics.py:20-22`,
  `run_backend_local.ps1:68-70`). The default is no listener. It is not the API.
- The local smoke and the load tool also call the advice GET, POST and job routes
  (`smoke_backend_local.py:158`, `:188` and `:224`; `advice_load.py:127` and `:147`).
- CI's browser acceptance builds the site against its own local backend, not the
  repository variable (`tests/integration/test_advice_browser.py`,
  `web/playwright.backend.config.ts:30`).
- The manual live smoke reads the capabilities when they answer. With
  `LIVE_SMOKE_COMPUTE=1` it requires them (`web/e2e/live-smoke.spec.ts:161-165`), so that
  option cannot pass on a site built without an origin. `docs/deployment_runbook.md:552`
  names the option.

## Lost until the device path covers it

- **3 and 5 week plans the weekly publish did not write.** At most, the publish writes the
  pure-points plan at 3 and 5 weeks, and the rival strategies over those windows against
  the default rival (`src/squadopt/application/league_views.py:541-547` and
  `:1283-1287`). Any other multi-week selection is computed only on request. #984 covers it
  only if its verdict says device. #981 step 8 later moves 352490 to the device menu,
  whose publish solves no member (#981 step 6).
- **Preferences:** keep, avoid, no paid transfers and save chips. Without capabilities a
  preferences address resolves to not listed (`adviceSelection.ts:393-401`), and the device
  refuses it (`selection.ts:58-65`). #1001 steps 1 to 3 bring them to the device at window
  one. Over 3 and 5 weeks they follow #984's verdict.
- **The football model as a member option**, with the model comparison
  (`LeagueMemberView.tsx:538`) and the new information notice, which only a football plan
  shows (`OfficialInformationCard.tsx:86-100`). Nothing replaces it. #1001 default b lets
  the option go with route 1, and #1001 step 5 keeps the weekly football build.
- **The manager's word beyond the published documents.** The publish writes the one-week
  manager's-word documents (`league_views.py:1296-1301`). The device does not take the
  switch (`selection.ts:60`, `docs/contracts/league_device_plan_v1.md:141`), and #1001
  lists it as not in scope. No issue covers it on the device.
- **A rival strategy at a Top 100 weight against a rival other than the default.** The
  device declines that pair by contract (`league_device_plan_v1.md:120-123`). No issue
  covers it.
- **Contribute.** Nothing replaces it. #1001 step 4 hides it without an origin.

## Still to decide

- **Contribute and its store.** #1001 hides Contribute and deletes nothing (its default c).
  The comments are in `contributions.sqlite3` under the backend store root on the owner's
  PC, moderated with `scripts/moderate_contributions.py` (see `docs/contributions.md`).
  Whether that file is kept, exported or retired, and whether pending comments are
  moderated before the backend stops, is not decided on #988.
- **The release without an origin.** Building the site without `VITE_ADVICE_API_ORIGIN`
  and releasing it needs the owner's yes, as every release does. The variable is also
  named in `docs/architecture/operations_inventory.md`. Per #988 (comment 6045439960),
  the release waits for #1001 steps 1 to 4 to merge, unless the owner records on #988
  that it ships without them.
- **The uptime schedule.** `backend-uptime.yml:6-7` probes `/health` and `/ready` every
  15 minutes. Route 1 turns the schedule off in its own PR.
- **Offline callers of backend modules.** `squadopt.platform.capture_context` is imported
  by `scripts/check_football_prospective_inputs.py`,
  `scripts/measure_member_plan_determinism.py`, `scripts/measure_member_window_proofs.py`
  and `scripts/measure_planner_policy_chain.py`, and draft #1046 adds a fifth caller. A
  route 1 PR that removes backend code keeps or moves that module (#988 comments from
  #1007 and #1009). The served football artifact root stays a Friday step under #1001
  step 5.
