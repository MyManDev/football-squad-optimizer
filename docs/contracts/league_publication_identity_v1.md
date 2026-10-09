# League publication identity

`publication-identity.json` binds one league's current members and human entry files
to its retained scoreboard, history and series-horizon set. It contains no forecasts
or runtime paths. Weekly preparation validates the inherited record once before
copying a published tree into its preview. The league and scoreboard writers can
resume interrupted writes in that preview, then record the completed set. The stage journals
the final identity file. The GW5 settled writer follows the same rule on its scratch
candidate, keeping the current decision capture distinct from the outcome capture.

The record carries `contract_version: league_publication_identity_v1`, the current
`source_snapshot_id`, league, season and gameweek, and `files`. Every rendered human
entry must name that same decision capture, league, season and gameweek. A member
explicitly marked `data_quality: empty` may have no entry file. The identity still
names the writer's decision capture when no member could be rendered.

`files` maps each protected relative filename to the SHA256 of its JSON document,
serialized with sorted keys, compact separators and no NaN. Paths are restricted to
`members.json`, `entries/<positive integer>.json`, `history/<positive integer>.json`,
`scoreboard.json` and `series-horizon.json`. Every protected file on disk must be
listed, and every listed document must match. The remote release check verifies
every listed document; the disk check also verifies the complete file inventory.
Older historical captures are retained as their actual documents, never restamped
as the new decision capture. Their presence and contents travel as one recorded set.

The ready bundle seals the identity file and all retained documents beside its
current member and entry files. Its immutable file records additionally bind their
exact bytes. A changed, missing, extra or substituted protected document is refused
before the ready marker is written and again when the bundle is read.

Trees published before this record existed remain readable. The next normal league
publication establishes the record after validating and writing its current entries.
A new bundle with retained historical documents requires that record; it cannot
silently certify an unrecorded historical set. No fit or archive read is introduced.

If an approved editing PR intentionally changes a protected document outside the
normal writers, it must also re-record the identity in the same commit, using
`record_tree_identity(tree, source_snapshot_id=<the retained decision capture>)`
from `squadopt.application.league_tree_identity` after validating its complete set.
Review the new record with that editing PR. A changed-file or changed-inventory
refusal is not permission to remove or refresh a record on a served tree. A general
stale-record recovery command requires the owner's decision. Normal retry of an
interrupted preview uses the same run id and capture and finishes its own record.
