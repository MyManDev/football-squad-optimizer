# Private backup and recovery

The installed `squadopt.platform.backup_recovery` module creates an offline copy of
explicitly selected directories, verifies every file against a versioned SHA-256
manifest, and restores only into an absent or empty destination. It neither deletes
source data nor selects a retention policy. An immutable file or a checksum is not
itself an independent backup.

## Existing configuration and boundaries

The repository baseline inspected for this change is
`4ce5702db16759e7af89ea12c394e0edcd891f33` on 9 September 2026.

| Evidence | Consequence for a recovery set |
| --- | --- |
| `.gitignore` excludes `data/snapshots`, `data/ledger`, `data/handoffs`, `data/entries`, `data/advice_records`, `data/logs` and `data/runtime` | Git alone cannot recover these private operational bytes. |
| `data.snapshots` binds payload checksums to capture metadata; `live.ledger` and `application.advice_record` verify their own immutable records | Keep the whole selected roots together; retain domain manifests as well as this backup manifest. |
| `deploy/containerapp.yaml` separates the store and read-only inputs mounts; `docs/backend_runbook.md` configures four backend roots | Source paths must be supplied explicitly. The command does not guess that a local `data` folder is the deployed store. Include the configured runtime store if its jobs/cache/provenance are required. |
| The checked workflows contain seven-day **CI artifact** retention, but no private backup job; the deploy template contains no backup resource | CI site artifacts are not a private-data backup. No repository evidence establishes an external backup account, recovery objective or deletion schedule. |
| No `SQUADOPT` backup/root/retention environment variable was set in the inspected command environment | This is local configuration evidence, not a cloud inventory. Host/cloud settings remain unverified. |

Captures, permanent ledger/advice history, current and retained handoffs, registry and
any evidence/archive inputs needed to reproduce the selected computation belong in
the operator's recovery inventory. Runtime records may contain path references: their
bytes are preserved, not rewritten to claim a new location. Verify/configure those
references before using restored runtime history. Optional roots are not silently
excluded; missing directories fail rather than produce a deceptively complete backup.

The operator must record which roots are authoritative, which may be rebuilt, their
owner, the consistency boundary, storage access/encryption, recovery objectives and
retention. This implementation makes none of those unknown business decisions. There
is no automatic pruning and no new paid or network service.

## Consistent offline creation

Stop the publisher, capture writers, ledger/advice-record writers, API submitters and
workers that can write the selected roots. Prevent them restarting until creation has
finished. `--writers-stopped` records that operator precondition; it does not stop
processes or prove that they are stopped. Before/after inventories detect a source
change but cannot create a transaction across running writers.

Choose an independent, access-restricted destination outside **all** selected roots.
The directory must not exist, or must be empty; its parent must already exist. A copy
on the same disk is a useful drill, but not protection against losing that disk. The
tool writes plaintext bytes and does not preserve source ACLs, ownership, extended
attributes or timestamps; destination access/encryption belongs to the storage owner.

For example, with paths replaced by the actual configured private roots:

```powershell
python -B -m squadopt.platform.backup_recovery create `
  --root snapshots=C:/private/snapshots `
  --root ledger=C:/private/ledger `
  --root handoffs=C:/private/handoffs `
  --root entries=C:/private/entries `
  --root advice_records=C:/private/advice_records `
  --root store=C:/private/backend-store `
  --destination E:/restricted-backups/recovery-20260909 `
  --writers-stopped
```

An installed wheel supports this command without a repository `scripts` import.
The caller records the JSON receipt outside the backup directory; it contains the
manifest SHA-256, file count and total bytes. Keep that receipt in an independently
trusted, protected location. A matching self-edited manifest and file set are not an
authentic backup without that separately retained hash.

The directory contains `manifest.json` and `files/<root-name>/...`. The manifest uses
`private_backup_v1`, relative paths, sizes, hashes and the creation timestamp. Absolute
source paths are not embedded. Empty directories are retained. Symlinks, Windows
junctions/reparse points, overlapping roots/destinations, traversal, alternate streams
and nonportable/colliding paths are refused. No path is silently skipped.

File content is flushed before completion; `manifest.json` is written last, after
source and destination verification. A failed or interrupted operation leaves its
partial output for inspection and never merges into it on retry. A partial/truncated
manifest cannot pass verification. Use a new empty destination after investigating a
failure. File sync and atomic alias replacement do not establish host-power-loss or
remote-filesystem durability; those require acceptance on the actual storage.

## Verify and restore without overwriting live data

Stop all writers to the isolated restore target. Supply the manifest hash from the
creation receipt, not a freshly computed hash of a possibly modified manifest:

```powershell
python -B -m squadopt.platform.backup_recovery verify `
  --backup E:/restricted-backups/recovery-20260909 `
  --manifest-sha256 <recorded-64-character-sha256>

python -B -m squadopt.platform.backup_recovery restore `
  --backup E:/restricted-backups/recovery-20260909 `
  --manifest-sha256 <recorded-64-character-sha256> `
  --destination C:/isolated-recovery/drill-20260909 `
  --writers-stopped
```

Restore verifies the entire backup before creating output, copies without replacing
existing files, verifies copied bytes during transfer, then verifies the exact complete
restored tree. Missing, changed and unexpected files fail verification. Completion
returns a verified receipt and exit zero; failure returns exit one. There is no implicit
retry, startup of services, promotion to live paths or change to source configuration.

Before any cutover, read the restored captures with `read_snapshot`, ledger entries with
`load_entry`, the registry with `EntryRegistry.load`, handoffs with
`read_projection_handoff`, and captured advice history with `load_member_advice_record`.
Check their capture/fingerprint relationships and the selected publication hashes.
Configure the isolated service to those restored paths; assess captured queued/running
jobs through queue recovery before accepting traffic. A filesystem copy does not decide
which old jobs should execute. Record elapsed restore time, measured sizes, domain checks,
the recovery-point timestamp and service acceptance separately from backup completion.

## Preserve capture-specific handoffs

The projection producer retains both the old and new validated handoff bytes under:

```text
handoffs/by-capture/<source_snapshot_id>/<sha256-of-exact-file-bytes>.json
```

It preserves an existing legacy gameweek handoff before its first replacement, then
retains the new bytes before atomically replacing `<season>-gwNN.json`. That compatible
alias and `projection_handoff_v1` schema remain unchanged. Producer invocations must be
serialized. Identical bytes are idempotent; corrupted retained bytes stop publication.
The content hash deliberately differs from the projection fingerprint: diagnostics can
change without changing the latter, and both exact versions must remain available.
No history is deleted, and previously overwritten handoffs cannot be reconstructed.

This archive supplies rollback bytes; it does **not** change the backend's current
capture selection or automatically select a historical projection. To restore a previous
capture, choose the retained handoff by its recorded content hash, verify its embedded
capture/fingerprint, and restore the matching snapshot and legacy alias together while
serving is stopped. Merely withdrawing a same-week snapshot still leaves the wrong alias
until its matching handoff is restored. Include the complete handoff root in the backup.

## Acceptance still required on the real environment

The repository tests exercise synthetic offline bytes, corruption/missing objects,
interrupted copies, refusal to overwrite, retained capture history and the actual domain
readers after an isolated restore. They do not establish that an external backup exists.
No real private root was copied as part of implementation. An operator must still record
the destination/permissions, evidence that writers are stopped, a real isolated restore,
domain/service checks and measured recovery time before operational reliance. Decide
retention and recovery objectives from that evidence; do not infer them from the CI
artifact's seven-day setting.
