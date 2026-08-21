# Static site deployment runbook

Cloudflare Pages publishes only the static `web/dist` artifact produced by the successful
`web (node 22)` CI job. The deployment workflow downloads those already-tested bytes and never
rebuilds them. It does **not** host the FastAPI application in `src/squadopt/api`; backend
hosting is a separate future decision.

The current site fits the Cloudflare Pages Free plan. Static asset requests are free and
unlimited; the operating budget assumes 500 deployments per month, 20,000 files per site, and
25 MiB per file. Recheck the official [Pages overview][pages], [Pages limits][pages-limits],
and [Functions pricing][functions-pricing] before adding server-side code.

## Immediate credential rule

Any API token pasted into chat, a ticket, a command-line argument, or a log is compromised.
Revoke it without testing it. Create a replacement only after the trusted workflow and GitHub
Environment are ready, and enter it directly into GitHub; never send it to another person or
tool in plaintext.

## One-time setup

1. Create a **Direct Upload** Pages project. `squadopt` is the suggested project name if it is
   available, and `main` must be the production branch:

   ```console
   npx wrangler@4.123.0 login
   npx wrangler@4.123.0 pages project create squadopt --production-branch main
   ```

   Cloudflare does not connect to the repository or build the application. Direct Upload
   projects cannot later be converted to Git integration; that is intentional here.

2. In GitHub, create an Environment named `cloudflare-pages`. Configure its deployment branch
   rule to allow only the selected branch `develop`. Do not allow arbitrary branches or tags;
   both trusted preview and production jobs execute from the default branch.

3. In Cloudflare, create a token scoped to the selected account with only **Account →
   Cloudflare Pages → Edit**. Do not grant Zone, Workers, or unrelated account permissions.

4. Add the account ID and replacement token as **Environment secrets**, then add the project
   name as a repository Actions variable. Each `gh secret set` command prompts securely; do not
   append the value to the command:

   ```console
   gh secret set CLOUDFLARE_ACCOUNT_ID --env cloudflare-pages
   gh secret set CLOUDFLARE_API_TOKEN --env cloudflare-pages
   gh variable set CLOUDFLARE_PAGES_PROJECT --body squadopt
   ```

5. Merge the deployment workflow before adding secrets. Confirm a same-repository PR against
   `develop` that changes `web/**` receives a `pr-N` preview and that a Python/docs-only PR is
   reported ineligible without entering the credentialed deployment job.

Before every upload, the trusted workflow reads the Pages project through the API and refuses
to continue unless it is a Direct Upload project whose configured production branch is exactly
`main`. This catches a Git-connected or wrong-branch project before it can create extra or
misclassified deployments.

The Pages project API supplies the actual `*.pages.dev` subdomain. Do not derive it from the
project name: Cloudflare may add a uniqueness suffix. A PR numbered 123 receives `pr-123.` in
front of that returned subdomain. The workflow validates and records both aliases. There is no
automatic `develop` deployment and a merge to `main` does not publish by itself.

## Preview flow

After successful CI, the trusted workflow reads the PR file list. It deploys only when all of
these conditions hold:

- the PR is still open against `develop`;
- its head is in this repository, not a fork;
- the successful run belongs to the current PR head SHA;
- a changed path, including a rename source, is under `web/**`.

The job downloads CI's `site` artifact into a temporary directory. It never checks out the PR
branch or runs code from the artifact. Trusted default-branch tooling rejects executable Pages
content, symlinks, malformed required assets, and Cloudflare file limits before upload.

## Production release — manual, tagged, no cron

Every production publication uses a new annotated tag on the exact `main` revision whose CI
artifact will be transported. Use phase-qualified tags; never move or reuse one:

```text
site-2026-27-gw01-decision
site-2026-27-gw01-settled
site-2026-27-gw01-fix1
```

After the relevant site-data revision is merged to `main` and its push CI is green:

```console
git switch main
git pull --ff-only
git tag -a site-2026-27-gw01-decision -m "Publish GW01 decision view"
git push origin site-2026-27-gw01-decision
gh workflow run deploy-pages.yml --ref develop -f release_tag=site-2026-27-gw01-decision
```

The workflow refuses lightweight/missing tags, tags outside `main` history, missing/failed CI,
expired/multiple site artifacts, and dispatches from any ref other than the default branch.
After upload it reads the returned deployment ID from Cloudflare and verifies the environment,
branch, commit SHA, success state, and ownership of the expected alias. It then smokes the
canonical production alias and records the exact tag, peeled SHA, CI run, deployment URL, and
result. Wait for the deployment workflow to finish successfully; a manual dispatch is not
complete merely because the upload step started or an older canonical page still answers.

There are two normal publications per gameweek from GW2 onward:

1. **Decision:** after the ~15:30Z capture/decision and human checks, regenerate
   `web/public/data`, merge the release revision to `main`, tag it `...-decision`, dispatch, and
   require green smoke before the 17:30Z deadline.
2. **Settled:** after outcomes are settled, regenerate the public data and season summary,
   merge to `main`, tag it `...-settled`, dispatch, and require green smoke.

No cron is used: a person is already operating the deadline, and only that person knows the
decision has been accepted. GW1 on 2026-08-21 is a documented one-off exception: its approved
run sheet publishes the decision view after the deadline. The pre-deadline order above becomes
canonical at GW2.

## Daily circuit breaker

The workflow queries all deployments for this Pages project in the current UTC day and
serializes budget-check-plus-upload in one repository-wide FIFO queue.

- Previews stop with a warning once the project has eight deployments that day.
- Production is permitted through deployment ten and then fails visibly.
- Failed and cancelled Cloudflare records count. Every eligible successful CI run uploads;
  previews are not deduplicated by head SHA because the tested merge base may have changed.
  Production always uploads so a manual dispatch reasserts the canonical project alias.

The two reserved slots permit a production attempt and one retry. This is an emergency stop;
`web/**` filtering and deliberate production dispatch are the real volume controls. Dashboard
and local Wrangler uploads do not share GitHub's queue. Before a manual upload, confirm no Pages
deployment job is running or queued and inspect the Cloudflare daily count.

## Post-deployment smoke

The trusted smoke test checks `/`, `/moves`, `/rivals`, `/league`, `/analysis`, `/status`, and
`/data/index.json`. All seven requests must return HTTP 200. Six routes must return the SPA
document; the data endpoint must parse as JSON and carry the short-lived revalidation policy.
Transient edge/propagation failures are retried for roughly one minute.

Run the same check from any machine with Node 22 when diagnosing a deployment:

```console
cd web
npm run smoke:deployment -- https://deployment.example
```

## Exact-artifact manual fallback

Use this only if the trusted deployment workflow is unavailable. Start from the immutable site
tag and find the successful `main` push CI run with the same SHA. Never choose merely the latest
run and never run a local build.

```console
git rev-list -n 1 site-2026-27-gw01-decision
gh run list --workflow CI --branch main --commit <tag-sha> --event push --status success
gh run download <run-id> --name site --dir site-<run-id>
npx wrangler@4.123.0 pages deploy site-<run-id> --project-name <project> --branch main --commit-hash <tag-sha> --commit-message release:site-2026-27-gw01-decision --commit-dirty=false
```

Use a new, empty `site-<run-id>` directory so retained bytes cannot mix with another run. First
confirm the GitHub deployment queue is empty and Cloudflare remains below the hard daily cap.
Run the smoke command immediately against the production alias printed by Wrangler.

## Rollback

In Cloudflare, open **Workers & Pages → project → Deployments** and select the previous
known-good production deployment by its site tag and commit SHA. Roll it back, run all seven
smoke checks, and record that tag as the live version. Do not move a tag, reset `main`, or
rebuild old source.

If content was wrong, correct or revert it through `develop` and `main`, then publish a new
`...-fixN` tag. If only transport failed and the CI artifact is still retained, redeploy that
exact artifact.

[functions-pricing]: https://developers.cloudflare.com/pages/functions/pricing/
[pages]: https://developers.cloudflare.com/pages/
[pages-limits]: https://developers.cloudflare.com/pages/platform/limits/
