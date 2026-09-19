# Static site deployment runbook

Cloudflare Pages publishes only the static `web/dist` artifact produced by the successful
`web (node 22)` CI job. The deployment workflow downloads those already-tested bytes and never
rebuilds them. It does **not** host the FastAPI application in `src/squadopt/api`; the backend
is hosted beside Pages, not inside it ([ADR 0006](architecture/decisions/0006-backend-hosting.md),
`deploy/compose.yaml`), and has its own runbook, [backend_runbook.md](backend_runbook.md).

The current site fits the Cloudflare Pages Free plan. Static asset requests are free and
unlimited; the operating budget assumes 500 deployments per month, 20,000 files per site, and
25 MiB per file. Recheck the official [Pages overview][pages], [Pages limits][pages-limits],
and [Functions pricing][functions-pricing] before adding server-side code.

## The address members open

The Pages project serves two hostnames. **`https://squadopt.mymandev.com` is the canonical
one**: it is the address given to members, the only one reachable from their networks, and the
origin their browsers send. The project's `*.pages.dev` subdomain remains the deployment alias
— CI smokes it, identity verification resolves it from the API, and it works fine from GitHub
Actions — but it is not a link to hand to anyone.

`pages.dev` is filtered on the hostname from the owner's network. Measured on 2026-09-09: TCP
to `squadopt.pages.dev:443` completes in about 29 ms and the peer then resets the connection
before any TLS record, identically on the apex, on a per-deployment alias, and on an unrelated
`*.pages.dev` site. `developers.cloudflare.com` answers 200 over the same path, and still
answers 200 when curl is forced to send that request to the address `squadopt.pages.dev`
resolves to — while sending SNI `squadopt.pages.dev` to the address that just answered gets the
reset. So it is the name, not Cloudflare, the IP, or the deployment.
`docs/handover_2026-08-23.md` recorded the same unreachability from a second network on
2026-08-23. The custom domain passes the full smoke gate (below) and serves the current data.

## Immediate credential rule

Any API token pasted into chat, a ticket, a command-line argument, or a log is compromised.
Revoke it without testing it. Create a replacement only after the trusted workflow and GitHub
Environment are ready, and enter it directly into GitHub; never send it to another person or
tool in plaintext.

## One-time setup

1. Create a **Direct Upload** Pages project. The project is named `football-squad-optimizer`
   (its `*.pages.dev` alias is `squadopt.pages.dev` — the project name and the hostname
   differ), and `main` must be the production branch:

   ```console
   npx wrangler@4.123.0 login
   npx wrangler@4.123.0 pages project create football-squad-optimizer --production-branch main
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
   gh variable set CLOUDFLARE_PAGES_PROJECT --body football-squad-optimizer
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

1. **Decision:** after the capture/decision and human checks, regenerate
   `web/public/data`, merge the release revision to `main`, tag it `...-decision`, dispatch, and
   require green smoke before the deadline.
2. **Settled:** after outcomes are settled, regenerate the public data and season summary,
   merge to `main`, tag it `...-settled`, dispatch, and require green smoke.

No cron is used: a person is already operating the deadline, and only that person knows the
decision has been accepted. GW1 on 2026-08-21 is a documented one-off exception: its approved
run sheet publishes the decision view after the deadline. The pre-deadline order above becomes
canonical at GW2.

### Which days those two land on

The agreed rhythm is **twice a week, settled on Tuesday and decision on Friday**. Tuesday
because the week's own results are the thing a member comes back for and they are not final
until the last fixture is checked; Friday because that is where the next deadline usually sits.

**The two publications have roles, not weekdays, and the deadline decides.** Tuesday and Friday
are where those roles land for most of the season, not a rule that outranks the calendar. Of the
38 deadlines this season, 25 fall on Saturday, 6 on Friday, 3 on Wednesday, 2 on Tuesday and 2
on Sunday, so a Friday decision run is in time for 33 of them. **Five are midweek and need their
own day:** GW13 (Wed 2 Dec), GW18 (Tue 29 Dec), GW20 (Tue 5 Jan), GW25 (Wed 10 Feb) and GW28
(Wed 3 Mar). For each of those, the preceding Friday is 126.5 hours before the deadline, so a
fixed Friday run would decide the week on a capture more than five days stale — before team
news, before injuries, before price changes. Move the decision run to the day before the
deadline for those five and keep the capture lead time from `docs/weekly_runbook.md`.

**The Tuesday run may publish nothing, and that is a pass, not a failure.** A gameweek counts as
settled only when the source says both `finished` and `data_checked`
(`application/scoreboard.py`), so a Tuesday that arrives before the check publishes "not settled
yet" rather than a wrong number. Confirm the week is checked before spending a run:

```bash
curl -s https://fantasy.premierleague.com/api/bootstrap-static/ \
  | python -c "import json,sys; [print(e['id'], e['finished'], e['data_checked']) for e in json.load(sys.stdin)['events']]"
```

**A run inside a fixture gap is not automatically safe.** Nothing in `weekly_operations` refuses
a gameweek whose deadline is weeks away: `--expected-at` inspects a finished run's status and
guards nothing, and `league`, `site` and `scoreboard` are unconditional stages. Between GW5
(18 Sep) and GW6 (10 Oct) there are 22 days, and six of the eight Tuesday/Friday slots in that
span fall inside the gap. Run the loop there and it will publish a GW6 plan more than a
fortnight early, from a capture that cannot know the team news, with nothing on the page saying
so. Inside a gap, publish the settled view once and then stop until the next deadline is inside
the lead-time window.

## Release in one command

The release recipe is in `scripts/release/`. Run it from the main checkout, not a
linked worktree. With Git and GitHub CLI available (Git Bash on Windows), preview
it first. The [weekly runbook](weekly_runbook.md#from-a-recorded-preview-to-a-release)
describes `--record-advice`, `--publish-suffix` and unchanged resume options before
this release stage:

```sh
sh scripts/release/ship.sh --dry-run 618 site-2026-27-gw05-fix8 \
  release/gw05-fix8 2026-09-18T17:00:00Z 'Publish the accepted decision tree.'
```

Replace the example's site PR, unused tag, release branch, content timestamp and
summary with the accepted publication. Read the exact `generated_at_utc` from
`web/public/data/league/members.json` in that accepted candidate tree. Verification
requires equality: the same tag can be re-dispatched, an older rollback refuses,
and a fix release requires its own accepted stamp. A matching stamp identifies
the publication claimed by that document; it is not a whole-tree byte comparison.
A settled release also requires its gameweek as the sixth argument (for GW5, append `5`).
The dry run prints every step and performs
no network requests or writes. Remove `--dry-run` only when operating the release.
The script waits for the site PR to merge, creates a two-parent release whose tree
equals develop, waits for the release PR to be clean and merges it with a merge
commit. It then waits for successful main push CI at the exact SHA with one
unexpired site artifact, creates the annotated tag, dispatches the trusted workflow
and checks the live site. Existing remote tags refuse. Choose a fresh release
branch: the recipe removes an existing local worktree and branch with that name.

## The release window is closed to develop

`deploy.sh` requires `origin/main`'s tree to equal `origin/develop`'s. `ship.sh` cuts the
release from the develop it read when it started, so **nothing may merge into develop from the
moment `ship.sh` starts until the tag is pushed.** One unrelated pull request landing in that
window makes the trees differ and `deploy.sh` refuses with `main tree != develop tree`, at a
point where main already carries the release tree and no tag exists yet. Neither script recovers
from that: running `deploy.sh` again meets the same check, and running `ship.sh` again fails its
own two-parent check because main already contains develop. The way out is another release merge
under a fresh branch and a fresh tag.

The window is not short. The waits are 60 minutes for the site pull request, 45 for the release
pull request and 40 for main CI. Before starting, stop the develop queue and let anything already
merging finish. Say so to anyone else merging that day.

**The point of no return is the line `release PR #N merged`.** Before it, stopping `ship.sh`
costs nothing: the worktree and the branch are local and nothing has been pushed to main. After
it, `ship.sh` must never be run again for that release, and this is the trap: if develop has not
moved, a rerun stops with `commit failed`, a message that does not mention the half-done release;
if develop **has** moved, the rerun succeeds and ships a different tree than the one the site
pull request reviewed, with no gate anywhere catching it. Recover with the second stage alone:

```
sh scripts/release/deploy.sh <tag>
```

and, once the tag has been pushed, with a re-dispatch instead, which needs neither script and
can be repeated:

```
gh workflow run deploy-pages.yml --ref develop -f release_tag=<tag>
```

Each dispatch that reaches the upload spends one of the day's ten Cloudflare deployments,
whatever happens after it, so a run that uploads and then fails its smoke check has still spent
one. Previews spend from the same day and stop at eight; on a busy day the previews can be gone
before 06:00 UTC, leaving two production slots. Check what the day has spent before dispatching.

`deploy.sh <tag>` is the second stage. `verify_live.py <accepted-generated-at-ISO> [--settled <gameweek>]`
retains the eleven smoke checks and the content checks, and a settled release names the gameweek it settles so the verifier asserts it. `queue2.sh <PR>...` is the separate
develop queue: it rebases existing PR worktrees, waits for clean checks and squash
merges with `clean_body.py` removing attribution lines. It is not the release-to-main
path. These are operator commands, not scheduled jobs; inspect their output and stop
on any refusal. GitHub CLI is found on PATH, with the usual Windows installation as
a fallback. No machine-specific repository or scratch path is required.
The scripts prefer the checkout's `.venv/Scripts/python.exe` or `.venv/bin/python`,
then Python on PATH, and verify that the interpreter starts before waiting or
changing anything. Missing GitHub CLI refuses immediately. The three release waits
are bounded to 60 minutes for the site PR, 45 for the release PR and 40 for main CI.
Interrupting the queue stops it and cleans up its temporary bodies. A body that
cannot be read or is empty after cleaning is never merged.

After the public release verifies, the owner runs these from PowerShell in the clean
main checkout on `develop`. **First check the backend is answering**, with a single local
`GET http://127.0.0.1:8000/ready` or `python scripts/backend_status.py`: the restart helper
reads the launcher registry and the loopback metrics before its own error handling begins, so
against a backend that is not running it stops on a raw exception and prints none of its
recovery guidance. It can only replace a running backend, never start one. If it is down,
pull develop by hand and start the backend with `run_backend_local.ps1` instead, then carry
on. The processes belong to the logon session and nothing restarts them, so a logoff or a
reboot between the publish and this step leaves nothing to restart. Replace `<same-ISO>` with the accepted candidate timestamp
used for `ship.sh`. First preview the restart:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\release\restart_backend.ps1 -AcceptedGeneratedAt <same-ISO> -DryRun
```

Only for the intended restart, run the same command without `-DryRun`:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\release\restart_backend.ps1 -AcceptedGeneratedAt <same-ISO>
```

The script verifies the public site, requires the public capture to match the fetched
`origin/develop` publication, refuses open work unless `-Force`, and pulls with
`--ff-only` before stopping the recorded backend.
It keeps the recorded port and worker count, requires `/ready` and its published-week
check, and verifies the new **launcher-recorded** commit against the pulled checkout.
The pre-pull local capture is information only; the pulled tree must match before any
process is stopped. It imports both backend entry points from the pulled source before
stopping. The launcher resolves its commit independently of any inherited override.
It does not claim an API-reported commit and never touches the tunnel. Dry-run performs
the read-only checks and prints inputs and `-Stop -WhatIf` targets without pulling or
changing processes. It does run `git fetch origin develop` to check the current
candidate publication and prints that remote-tracking state was updated; the working
tree and backend files stay unchanged. Real execution fetches as well. The helper requires
the launcher's creation-time-checked process walk and `-Stop -WhatIf` support. A failed
start or readiness check exits nonzero with a backend up/down state, the exact start
command retaining the recorded port and worker count, the log directory and the last
readiness body. A failed stop prints the stop command before the start command; a
ready backend on a different revision is reported as `BACKEND UP, WRONG REVISION`
with both hashes. Inspect those before another attempt: a timed-out launcher may still be
starting, and a failed stop may have left recorded processes alive. After a successful
stop or failed-start cleanup the PID registry may be gone; use the printed start command
instead of rerunning the restart helper, which cannot recover the old count without it.
For an operator-approved rollback, use that start command with
`-SourceRoot "<existing-worktree-of-the-previous-commit>\src"`, then verify readiness and
the recorded commit. Do not move tags or change the published tree as part of this step.
The helper supports the default backend configuration. A backend launched with custom
snapshot, handoff, artifact, club-news, origin, rate-limit or worker-metrics options must
be restarted by hand with those same options; the registry does not record them.
The first production use is the owner's operation, not part of development verification.

The complete operator order is: accept the recorded weekly tree, release the site,
drain the backend queue, preview then run the restart command above from clean
`develop`, and run the [manual browser check](#post-deployment-smoke). Both `ship.sh`
and the restart helper run `verify_live.py`; to run it again by hand, use
`python scripts/release/verify_live.py <accepted-generated-at-ISO> --settled <gameweek>`. A zero queue depth
permits a restart; `-Force` is an explicit operator exception, not the normal command.
`/ready` alone does not prove capture-ID or code-commit equality: its published-tree
check is season/gameweek. `ship.sh` publishes the site only and does not restart the
backend or tunnel.

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

After `verify_live.py`, run `cd web && LIVE_BASE_URL=https://squadopt.mymandev.com npx playwright test --config playwright.live.config.ts`; this manual desktop/phone check is read-only, and optional `LIVE_SMOKE_COMPUTE=1` checks the public backend with a browser GET, reporting a matching cached answer or `NOT_COMPUTED` (never submits a solve).
In PowerShell, run from `web`: `$env:LIVE_BASE_URL='https://squadopt.mymandev.com'; npx playwright test --config playwright.live.config.ts`.
For the backend mode, set `$env:LIVE_SMOKE_COMPUTE='1'` before that command.

The trusted smoke test makes **eleven** checks, and they are not all "must return 200". The list
lives in `SMOKE_CHECKS` in `web/scripts/smoke-deployment.mjs` and is the authority; this
paragraph is a reading of it, not a second copy to keep in step.

Eight are routes that must return HTTP 200 carrying the SPA document: `/`, `/moves`, `/rivals`,
`/league`, `/league/members/0`, `/analysis`, `/status`, `/fixtures`. The nested member path is there
deliberately, because a path-scoped not-found rule would break a nested client-side route first
and nothing else on the list would notice.

Two are published documents that must return 200, parse as JSON, and carry the short-lived
revalidation policy: `/data/index.json` and `/data/league/members.json`.

**The eleventh is the opposite check, and reading it as a 200 inverts it.**
`/data/league/entries/0.json` must be **absent**. Entry 0 does not exist, so a deployment that
answers anything but a not-found there has lost the rule that an absent document answers 404
rather than the application shell. A green smoke is eight route 200s, two JSON 200s, and one 404.

Transient edge and propagation failures are retried for roughly one minute.

Two routes are **not** in the gate and their absence is worth knowing before someone assumes
otherwise: `/gw/:season/:gameweek`, and `/admin`, which was added later. Neither is covered.

Production runs it twice: once against the `pages.dev` alias, then against
`https://squadopt.mymandev.com`. Both must pass. The second run is what makes a publication
that never reached the address members open fail instead of reporting green; it is not
retried differently, because the same one-minute budget covers alias propagation on either
hostname. Preview deployments run the alias check only — custom domains serve the production
branch, so a `pr-N` preview never appears on the canonical host.

Run the same check from any machine with Node 22 when diagnosing a deployment. Note that
`pages.dev` will fail from a filtered network; use the canonical host there:

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

## Back up irreplaceable data

From the source checkout, run `powershell -ExecutionPolicy Bypass -File scripts\backup_data.ps1 -Destination '<existing-backup-directory>' -DryRun`, then remove `-DryRun` to copy snapshots, ledger, handoffs, advice records and entries. Choose a second physical drive outside every repository worktree; synced folders such as OneDrive can carry reparse-point attributes and are deliberately refused; all five source trees must exist, and reparse points are refused. The script never reads runtime/raw or changes the source, never deletes old backups, and preserves conflicts as stamped files named by that run's manifest. A new conflict exits nonzero and lists the finding; an existing variant with the same hash is reused. Paths with any dot-prefixed component are transient by repository convention and are excluded, including from older manifests. Each run reports the excluded source count and a bounded sample, plus the count ignored from an older manifest. Source files missing since the last manifest raise a nonzero alarm with a bounded sample and total count; new files still copy additively, but no new manifest is written. Restore the lost files or explicitly run `-AcceptMissing` to acknowledge the listed loss and write a new manifest; it never deletes old backup files or manifests. `-AcceptMissing` is never part of the scheduled task: a person types it only after inspecting the loss list. Run the same command with `-Verify` to compare both sides with the latest manifest; a missing, changed or unrecorded source file fails. To restore, stop writers first, copy each manifest entry's `destination_path` from the backup to its `path` under the restored checkout's `data`, then run `-Verify -Manifest <that-manifest-name>`; the name must be a `manifest-*.json` file within the backup directory. After restoring an older recovery point, a plain backup can report newer files as missing against the latest manifest: inspect that list, then use `-AcceptMissing` if the older state is intentional. Do not blindly copy a stale canonical file over its newer conflict variant. The first real backup and restore have **never been exercised** here: only temporary fixtures were used. The scheduled task must run as the owner with Git on PATH. The scheduled action appends output to a log outside the repository and preserves the exit code; Task Scheduler alone retains only the last result. Scheduling is the owner's action; after replacing all three path placeholders, this PowerShell line registers a daily action (it does not run the backup now):

```powershell
Register-ScheduledTask -TaskName 'SquadOptDataBackup' -Action (New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -Command "& powershell.exe -NoProfile -ExecutionPolicy Bypass -File ''<repo>\scripts\backup_data.ps1'' -Destination ''<backup>'' *>> ''<outside-repository-log>''; exit $LASTEXITCODE"') -Trigger (New-ScheduledTaskTrigger -Daily -At '03:00')
```

## Rollback

The production workflow refuses a tag whose commit is behind or unrelated to the live
commit. Roll back through Cloudflare's dashboard, or publish a new `fixN` tag on a commit
ahead of live. After a dashboard rollback, the project serves that older deployment and
the next workflow release is compared with its commit. This rollback procedure has never
been exercised.

In Cloudflare, open **Workers & Pages → project → Deployments** and select the previous
known-good production deployment by its site tag and commit SHA. Roll it back, run the full
smoke gate (`npm run smoke:deployment -- https://squadopt.mymandev.com`), and record that tag
as the live version. Do not move a tag, reset `main`, or
rebuild old source.

If content was wrong, correct or revert it through `develop` and `main`, then publish a new
`...-fixN` tag. If only transport failed and the CI artifact is still retained, redeploy that
exact artifact.

[functions-pricing]: https://developers.cloudflare.com/pages/functions/pricing/
[pages]: https://developers.cloudflare.com/pages/
[pages-limits]: https://developers.cloudflare.com/pages/platform/limits/
