# React + TypeScript + Vite

This template provides a minimal setup to get React working in Vite with HMR and some Oxlint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the Oxlint configuration

If you are developing a production application, we recommend enabling type-aware lint rules by installing `oxlint-tsgolint` and editing `.oxlintrc.json`:

```json
{
  "$schema": "./node_modules/oxlint/configuration_schema.json",
  "plugins": ["react", "typescript", "oxc"],
  "options": {
    "typeAware": true
  },
  "rules": {
    "react/rules-of-hooks": "error",
    "react/only-export-components": ["warn", { "allowConstantExport": true }]
  }
}
```

See the [Oxlint rules documentation](https://oxc.rs/docs/guide/usage/linter/rules) for the full list of rules and categories.

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
