# Moving a gameweek to the backend VM

Since GW7 the VM's two Compose services do not read `~/squadopt/{site,snapshots,handoffs,
artifacts}`. `~/squadopt/.env` and `~/squadopt/compose.artifacts.yaml` point both services at
one immutable release directory, `~/squadopt/releases/<name>/payload/`, which holds the four
data roots and the club-news source of one capture. `scripts/vm_push.sh` predates that layout:
it rebuilds the image and restarts on the previous release's mounts, so the backend keeps
serving last week's capture while the command reports success. Use
`scripts/release/vm_football_release.py` instead.

## The five steps

All commands run on the PC from the repository root; `remote` runs a VM step over SSH and
uploads the script first. Host and key come from `SQUADOPT_VM_HOST` and `SQUADOPT_VM_KEY`.

1. **pack** copies the week's inputs into a package with a sha256 per file. Keep `--out`
   short (Windows path limit). The site tree is `web/public/data` at the release tag unless
   `--site-data` names another tree.

   ```bash
   python scripts/release/vm_football_release.py pack --gameweek 8 \
     --capture <fpl-live id> --tag site-2026-27-gw08-decision \
     --handoff data/handoffs/2026-27-gw08.json \
     --top100-manifest artifacts/phase_b/<the week's player_evidence manifest> \
     --news-capture <club-news id> \
     --rotation-manifest artifacts/rotation/<the week's rotation_evidence_v4 manifest> \
     [--windows-forecast-dir <dir with <capture>.json and <capture>.components.json>] \
     --out C:/sqp
   ```

   The Top 100 manifest names the cohort and picks captures, which travel with the decision
   capture and the club-news capture. The rotation manifest must name the same club-news
   capture and the same decision capture. Without a club-news capture the tag's committed
   fixture is packed and the manager's word stays unavailable.

2. **push** uploads the tarball, unpacks it under `~/squadopt/releases/<name>` with Python's
   data filter, and re-checks every byte against the manifest. A name that exists is refused.

3. **prepare** builds the image for the tag under a per-release image name (never moving a
   tag the live project names) from a separate checkout at `~/squadopt/build/<tag>`. When the
   package carries a football forecast, it renders the composite documents again from their
   retained recipe inside that image, bounds the difference from the Windows documents
   (derived values only, at most 1e-12 absolute), publishes them with the production
   publisher and seals the bundle with the week's news capture and rotation table.

4. **candidate** starts a second Compose project, `squadopt-candidate`, on ports 8001 and
   9191 with the release's mounts and a scratch store, waits for every readiness check,
   compares the capabilities with what the package implies (capture, models, manager's word),
   runs a window-1 advice job (and a football one when the package has the model), keeps the
   logs and the receipt in `<release>/candidate/<UTC stamp>/`, and stops the project. Trying
   again is harmless and activation reads the newest attempt. The live project
   is not touched.

5. **activate** keeps the live `.env`, override and repository commit in
   `<release>/rollback/`, checks the repository out at the tag, writes the release's
   configuration, restarts the live project and runs the candidate's checks against port
   8000. Any failure restores the kept configuration and restarts on it.
   `rollback --release <name>` does the same by hand.

`status` prints what the live project mounts and serves.

## Why the football forecast is rendered on the VM

`squadopt.live.football_composite_basis` reproduces the served result when it loads a
bundle. A forecast rendered on Windows differs from the Linux rendering in the last bits of
some derived floats (GW7: 8724 floats, at most 2.8e-14, and the 2405 hashes over them), and
both loaders refused it. The fitted models are inside the retained recipe, so the VM renders
again without fitting anything. The repository has no producer for the composite forecast
itself; the Windows documents come from the football model's own build.

## Package layout on the VM

```
releases/<name>/
  package.json            inputs and a sha256 per file, written by pack
  image.json              the image built for the tag
  payload/
    artifact_root/        phase_b/ (Top 100), rotation/ (manager's word), football/ (prepare)
    handoff_root/         <season>-gw<NN>.json
    snapshot_root/        decision, Top 100, picks and club-news captures
    site_data_root/       the published site data
    windows_forecast/     optional input to prepare
    club_news_fixture.json  only without a club-news capture
  rebuild-receipt.json    prepare, when football
  candidate/<stamp>/      env, override, logs, receipt.json, scratch store, per attempt
  rollback/ activation.json   activate
```
