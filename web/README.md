# SquadOpt member website

React + TypeScript + Vite front end for the published league-member views. It reads the
static `ui_view_v1` data tree that `python -m scripts.build_site` (a thin CLI over
`squadopt.application.site_publication`) writes under `public/`, and, when an advice
backend is configured, requests advice from it.

## Checks CI runs

The `web (node 22)` job in `.github/workflows/ci.yml` runs these from `web/`, in this
order, after `npm ci` and a Python `.[api,dev]` install for the last step:

| Step                                          | Command                                                                |
| --------------------------------------------- | ---------------------------------------------------------------------- |
| Types match the committed contract            | `npm run gen:types`, then `git diff --exit-code -- src/data/schema.ts` |
| Lint and format                               | `npm run lint` and `npm run format:check`                              |
| Typecheck                                     | `npm run typecheck`                                                    |
| Unit tests                                    | `npx vitest run`                                                       |
| Build                                         | `npm run build`                                                        |
| Deployment assets                             | `npm run check:deployment`                                             |
| Bundle budget                                 | `npm run size`                                                         |
| Playwright smoke                              | `npm run e2e` (after `npx playwright install chromium`)                |
| Publication and browser API worker acceptance | the pytest run below, from the repository root                         |

The last row runs, with `SQUADOPT_PUBLICATION_CONTRACT=1` and `SQUADOPT_BROWSER_SMOKE=1` set:

```sh
python -m pytest tests/integration/test_publication_contract.py tests/integration/test_advice_browser.py -q
```

Run the same list locally before opening a PR; the browser half is described below.

## Browser check with the real advice backend

The optional integration check starts the production uvicorn factory and a separate
one-job worker over a temporary local store. Chromium requests a plan for a synthetic
captured squad, displays the result, then requests it again after a page reload. The
second request must return the identical cached answer without creating another job.
No API responses are mocked; the browser also exercises the configured CORS allowlist.

Install the repository's `api,dev` Python extras, run `npm ci` and
`npx playwright install chromium` in `web`, then run from the repository root:

```powershell
$env:SQUADOPT_BROWSER_SMOKE = "1"
python -m pytest tests/integration/test_advice_browser.py -q
Remove-Item Env:SQUADOPT_BROWSER_SMOKE
```

On POSIX shells:

```sh
SQUADOPT_BROWSER_SMOKE=1 python -m pytest tests/integration/test_advice_browser.py -q
```

The test chooses local ports, stops its API/worker processes, and leaves diagnostic
logs in pytest's temporary directory. Its production-mode Vite build embeds the local
API origin in a unique `web/node_modules/.cache/advice-backend-smoke-*` directory; it does not replace
`web/dist`. The normal Python suite skips this opt-in check and the normal Playwright
suite retains its static-site scope. Run the check after backend or web advice
integration changes; it proves the local process boundary, not a deployed container
or cloud filesystem, and uses no historical measurements or live member data.
