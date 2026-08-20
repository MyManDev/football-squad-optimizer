# Static site deployment runbook

The site is deployed to Cloudflare Pages by the `deploy (cloudflare pages)` job in CI. It
downloads the `site` artifact produced by `web (node 22)`; it never rebuilds the site.

## One-time setup

1. In Cloudflare, create a **Direct Upload** Pages project and set its production branch to
   `main`:

   ```console
   npx wrangler@4 login
   npx wrangler@4 pages project create
   ```

   Record the chosen project name. `squadopt` is the suggested name if it is available.

2. Create a Cloudflare API token scoped to the selected account with **Account → Cloudflare
   Pages → Edit**. Do not grant zone or Worker permissions.

3. Add the account ID and token as GitHub **repository Actions secrets**, then add the project
   name as a repository Actions variable:

   ```console
   gh secret set CLOUDFLARE_ACCOUNT_ID
   gh secret set CLOUDFLARE_API_TOKEN
   gh variable set CLOUDFLARE_PAGES_PROJECT --body squadopt
   ```

   Replace `squadopt` with the actual project name. Never put the API token in a command-line
   argument, file, commit, organization secret, or Actions variable.

4. Run CI manually on `develop` or push this branch. Confirm the Actions summary contains a
   deployment URL and a branch alias. A pull request numbered 123, for example, is deployed as
   branch `pr-123` and normally receives an alias shaped like
   `https://pr-123.<project>.pages.dev`.

Production is `<project>.pages.dev` and is updated only by `main`. `develop` and pull requests
are previews.

## Post-deployment smoke

CI checks `/`, `/moves`, `/rivals`, `/league`, and `/data/index.json`. Run the same check from
any machine with Node 22 when diagnosing a deployment:

```console
cd web
npm run smoke:deployment -- https://deployment.example
```

All five requests must return HTTP 200; the four routes must return the SPA document and the
data endpoint must parse as JSON.

## Manual GW1 fallback

Use this only if automatic deployment is not ready. Select a successful CI run for `main`,
download its already-tested artifact, and deploy the extracted directory. Do not run a local
build.

```console
gh run list --workflow CI --branch main
gh run download <run-id> --name site --dir site
npx wrangler@4 pages deploy site --project-name <project> --branch main
```

The final command is the complete manual publish step. Immediately run the smoke command above
against the URL Wrangler prints.

## Rollback

In Cloudflare, open **Workers & Pages → project → Deployments**, select the previous known-good
production deployment, and roll back to it. Then reconcile `main` with a revert or corrective
release so repository history again describes production.

## Weekly release operation

After the 15:30Z tick, regenerate and commit `web/public/data`, let CI build the site, and merge
the settled release to `main`. Confirm the production deployment and smoke result before the
17:30Z deadline. If Cloudflare deployment fails, use the successful `main` CI artifact with the
manual fallback; never substitute an untested local build.
