# Club-news join counts of the GW8 decision run: pre-registration

Status: pre-registered on 2026-10-22, before the GW8 club-news capture, the GW8 decision
capture or any GW8 model response exists. It fixes the inputs, every count and its exact
computation, and the reading that decides #1006. It changes no stage of the weekly run, no
capture, no table, no member page and no contract, and it promotes nothing. Issues: #524,
#1006 and #1140.

Amended on the same day, on review and still before any GW8 data existed: a model call that
was attempted and failed now rules out `no_statement_lost`, the receipt is required, every
not-applied statement carries its cause, and the replay is held to the whole manifest and to
the commit the table was exported at. Amended again after it merged, on review of #1213 and
still before any GW8 data existed: see the next section.

## Amendment, 2026-10-22, before any GW8 data

Made after this protocol merged (#1213), on İbrahim's review there and the owner's decisions
in reply (comment 6342002217). No GW8 club-news capture, decision capture, model response,
rotation pair or record existed when it was made, so no GW8 number informed it. It merges
before the Friday run, so the commit the run's rotation manifest names carries it.

- **A next-match statement made before an intervening club match is not a loss.** A
  statement labelled `upcoming_premier_league`, on a page whose publication the reader
  verifies to an instant at or before the decision capture, is left out of
  `lost_unapplied`, as `other_competition` and `past` are, when the decision capture's
  calendar, read as the reader reads it, gives the club one dated target-gameweek fixture
  kicking off after the capture, no other club fixture at the same kickoff and no undated
  fixture that may come before it, and shows the club's first dated league fixture after that
  instant kicking off before the target fixture. It is counted by name as
  `next_match_before_target` (defined exactly under the
  reading below). The earlier match may kick off before or after the capture. Undated, blank
  and double target weeks stay losses under their existing causes, and so do the two cases
  this protocol reads as after the cutoff: a target fixture that kicked off by the decision
  capture, and a page published after it. Before this amendment such a statement was
  counted under `scope_unverified`, the cause where items 3 and 7 of #1006 act: the scope
  label comes from the quote's own words, so such a statement keeps
  `upcoming_premier_league`, and the rule rightly refuses to bind it to the target fixture,
  because it binds "next match" to the club's first kickoff after publication. İbrahim
  reproduced it with the reporter's own helpers: one such statement on an otherwise clean
  week turned `no_statement_lost` into `statements_lost` and routed items 3, 7, 4 and 10,
  while the same page published after the club's match read `close`. Neither item 3 nor
  item 7 could change that, because item 7's acceptance already requires no club match
  between publication and the target kickoff. Selection keeps pages up to seven days old, so
  the Friday run can code a page published before a club's GW7 match.
- **The reporter refuses code imported from another checkout.** It refuses unless
  `squadopt` is imported from the `src` directory of the checkout it runs from, because the
  commit check reads that checkout and the replay runs whatever code was imported.
- **Clarified, with nothing counted differently:** why a statement given
  `ambiguous_current_week_fixture` is not counted in `lost_unapplied`, and how that agrees
  with the "no single next match in the gameweek" case of `scope_unverified`.
- **The record's version is now `club_news_join_counts_v2`**, because the record gains
  `excluded_from_lost_unapplied`, and `lost_unapplied`, its `scope_unverified` cause and
  `lost_unapplied_scope_unverified_by_scope`, and with them `lost`, no longer count the
  statements named `next_match_before_target`. No record of version 1 was printed from GW8
  data. The inputs, every other count, the identities, the verdict table and the routing
  rule for #1006 are unchanged.

## Why this is written

- **#524.** The owner's closing condition, given on #1168 on 19 October (comment
  6276053750): one real-capture Friday run this season, the GW8 decision run on Friday
  23 October with club news on, plus the join-count record.
- **#1006.** The owner's decision of 19 October (comment 6276743450): the issue stays open
  until the GW8 join-count record shows whether club-news statements are being lost. With
  none lost it closes. With losses its data-zone items 3, 7, 4 and 10 go to İbrahim
  (`@SpeedyV5`), who owns club news (`docs/architecture/ownership.md`).
- **Nothing on develop reports these counts.** The exporter keeps the no-match,
  unknown-team, club-source and conflict counts (`claims_unresolved`) and the unverifiable
  citations (`claims_unverifiable_citation` and `players_with_unverifiable_citation`) only in
  the attributes of the table it builds in memory (`src/squadopt/features/rotation_evidence.py`).
  The manifest carries the ambiguous count (`claims_ambiguous`), the placed claims and the
  players with conflicting claims, and none of the others. Claims dropped about another club's
  players and identical repeats are counted nowhere (#1006 item 4). A club whose model call
  failed leaves nothing in the capture at all; only the acquisition receipt names it (#1006
  item 10).
- **The 21 October checkpoint** (#524 comment 6321111742) was a one-club scratch run, not the
  Friday run: capture `club-news-20261021T161737Z-ca7354f945c2`, one answered call, zero raw
  claims, eleven Liverpool documents; with the roster of
  `fpl-live-20261021T162132Z-877ebba8712d`, 668 rows, unique joins 0, no-match 0, ambiguous
  0, no refused response, no unverifiable citation, no constraining statement, no exclusion,
  and the reader's source check `nothing_cited`. It could not show a loss either way, and it
  is not this record.
- **The data exists only on the owner's PC.** The club-news capture, the decision capture, the
  acquisition receipt and the rotation pair are written there by the Friday run and are not
  in the repository. So the counting is fixed here, before the run, and is done there by a
  reporter that reads only those local files.

## What has been read

- Issues #524, #1006 and #1140 with every comment, and the owner's answers on #1168.
- On develop at `ce0c6431`:
  - `scripts/weekly_run.ps1`: the Friday launcher refuses a checkout that is not clean or not
    on develop, pulls develop, acquires news with no `--club` filter and the default budget
    of three model calls, keeps the acquisition output in
    `data/logs/weekly/<run id>.club-news.log` and passes the capture to the weekly command as
    `--rotation-capture`. The run id has the form `2026-27-gw08-friday-<yyyyMMddTHHmmZ>`.
  - `src/squadopt/platform/club_news_acquire.py`: the receipt's `Capture`, `Raw claims` and
    `Call budget` lines; the coverage report's `Read refusal:` and `Coding refusal:` lines and
    the coding stage's outcome lines (`src/squadopt/platform/club_news_coverage.py`); and the
    four kinds of coding refusal in `code_week` (`src/squadopt/platform/club_news_provider.py`).
  - `src/squadopt/application/rotation_export.py` (`_inputs_from_capture` and `_export`),
    `src/squadopt/features/rotation_evidence.py` (`build_rotation_evidence_table` and
    `_resolved_claims`), `src/squadopt/data/claim_identity.py` (`resolve_claim_player`),
    `src/squadopt/data/sources/club_news_coding.py` (`locate_claims_reporting`),
    `src/squadopt/data/sources/club_news_claims.py` (`parse_claim_response`) and
    `src/squadopt/application/manager_words.py` (the reader and `managers_word_rule_v3`).
  - `data/sources/club_news_sources.json`: Liverpool, Newcastle and Crystal Palace on three
    hosts, and the Example FC placeholder, which is refused before any request.
  - `docs/club_news_configuration.md` and `docs/club_news_sources.md`.

## Inputs, and how each is found after the run

Everything is on the publishing PC, in the checkout the Friday run used.

1. **The run id**, printed by the Friday launcher on its `friday run:` line, with the receipt's
   path on its `club-news log:` line.
2. **The acquisition receipt** `data\logs\weekly\<run id>.club-news.log`. Its `Capture` line
   names the club-news capture, `club-news-<stamp>-<hash>`; the launcher also prints it as
   `club news: capture <id>`.
3. **The club-news capture** `data\snapshots\<club-news id>`.
4. **The rotation pair** the weekly run exported from that capture:
   `artifacts\rotation\rotation_evidence_v4_2026-27_gw08_<last 12 characters of the club-news id>_decision_<last 12 characters of the decision id>.csv`
   and the `.manifest.json` beside it. The reporter finds it from the receipt's capture id and
   refuses unless exactly one table matches.
5. **The decision capture**, named by the manifest's `roster_snapshot_id`:
   `data\snapshots\fpl-live-<stamp>-<hash>`.
6. **The source registry** `data\sources\club_news_sources.json` as committed.

If more than one Friday run completes for GW8, the record is made for the run whose decision
capture the GW8 publish carries, and its Markdown names the other run ids as not counted.

## The command the owner runs

After the Friday run has finished, from the publishing checkout, still clean and still at the
commit the run used (the launcher pulls develop when it starts; a pull after the run moves the
checkout off that commit):

```powershell
.venv\Scripts\python -m scripts.report_club_news_join_counts --club-news-log data\logs\weekly\<run id>.club-news.log --output data\logs\weekly\<run id>.join-counts.json
```

`--club-news-log` is required: the receipt is the only record of which clubs' model calls
failed. The reporter prints the record as JSON and writes the same bytes to the `--output`
file, which must not exist yet; `data/logs/` is ignored by git, so the checkout stays clean
for the next run. It exits 0. On any refusal it prints one `Refused: <reason>` line, writes
nothing and exits 1; that line is posted in place of the record.

The reporter rebuilds the rotation table with the code of the checkout it runs from, so it
refuses unless that checkout is clean and its HEAD is the commit the rotation manifest names
(`repository_commit`). If the checkout has moved, or has local changes, it is run from a
worktree at that commit, with the worktree's own code first on the path, as the launcher sets
it:

```powershell
git worktree add ..\squadopt-gw8-counts <repository_commit of the manifest>
cd ..\squadopt-gw8-counts
$env:PYTHONPATH = "$PWD\src;$PWD"
..\<checkout>\.venv\Scripts\python -m scripts.report_club_news_join_counts --club-news-log ..\<checkout>\data\logs\weekly\<run id>.club-news.log --snapshot-root ..\<checkout>\data\snapshots --rotation-dir ..\<checkout>\artifacts\rotation --registry ..\<checkout>\data\sources\club_news_sources.json --output ..\<checkout>\data\logs\weekly\<run id>.join-counts.json
```

This needs the reporter at that commit, which is why it merges before the Friday run.

In both routes the reporter refuses unless `squadopt` is imported from the `src` directory of
the checkout it runs from. A publishing checkout whose virtual environment was built as
`docs/rebuild_production.md` describes installs the package from that checkout in editable
mode, so the first command passes; in a worktree only the `PYTHONPATH` line does. If it
refuses for this reason, set `$env:PYTHONPATH = "$PWD\src;$PWD"` in the checkout it runs from
and run it again.

## What the reporter reads, and when it refuses

It reads the snapshot store, the rotation pair, the registry and the receipt, and nothing
else. It opens no network connection, calls no model, and writes only the `--output` file.

It rebuilds the rotation table from the two captures through the exporter's own functions
(`_inputs_from_capture`, then `build_rotation_evidence_table` with the manifest's season,
gameweek and deadline), and holds the replay to what was published in three ways:

- the rebuilt bytes must hash to the manifest's `table_sha256`, which binds every row;
- the manifest rebuilt from the replay with the exporter's own writer and serialization must
  equal the published manifest in every field but `generated_at_utc`, which binds every
  attribute the manifest carries (`claims_coded`, `claims_ambiguous`,
  `players_with_conflicting_claims`, `players_not_addressed`, `clubs_covered`,
  `document_sha256s`, `response_sha256s` and the rest);
- the checkout must be clean and at the manifest's `repository_commit`, and `squadopt` must
  be imported from that checkout's `src`. The counts the manifest does not carry
  (`claims_unresolved` apart from its ambiguous entry, `claims_unverifiable_citation`,
  `players_with_unverifiable_citation`) are read from the replay's attributes, and only this
  binds them to the published run: the replay then runs the export's own code on the
  export's own captures.

It refuses, naming the reason, when:

- `squadopt` is not imported from the `src` directory of the checkout the reporter runs from
  (`Path(squadopt.__file__)`, resolved, is not under it), checked before anything is read.
  The commit check below reads the checkout `scripts/` sits in; without this guard, a
  worktree run that skipped its `PYTHONPATH` line would replay the main checkout's code under
  a passing commit check, and the counts the manifest does not carry would come from that
  code;
- the manifest's `club_news_source_kind` is not `capture` (the fixture is not club news);
- the checkout is not at the manifest's `repository_commit`, or has local changes;
- the receipt names a different capture from the manifest's `club_news_snapshot_id`, or no
  capture, or more than one;
- the receipt does not print its `Raw claims` line, its `Call budget` line and each of the
  coding stage's four outcome lines exactly once (every acquisition that writes a capture
  prints all of them), or an outcome line's count differs from the clubs it lists;
- the clubs those four outcome lines name differ from the clubs the capture holds pages and
  no answer for (`read_not_coded`);
- the club-news capture was not completed before the decision capture;
- the rebuilt table differs from the published one, or the manifest rebuilt from it differs
  from the published manifest;
- its own reading of the responses disagrees with the exporter's (refused responses,
  own-club unverifiable citations, claims reaching the join);
- the counts below do not add up, or `placed` differs from the table's observed rows or the
  manifest's `claims_coded`;
- the receipt's `Raw claims` line differs from `raw_per_coded_club`;
- the capture declares a club the registry does not register, or holds a document from a host
  no declared club registers.

## Every count, and how it is computed

The record's version is `club_news_join_counts_v2` (the amendment above). Its top level
carries `record_version`, `protocol` (this file), `reporter` (the script), `repository_commit`
and `repository_dirty` (the checkout the reporter ran from: the export's commit, and not
dirty, in a printed record), and the manifest's `season`, `target_gameweek` and
`deadline_timestamp_utc`.

### `inputs`

`club_news_capture_id` and `club_news_captured_at_utc` (the news capture's id and completion
instant), `decision_capture_id` and `decision_captured_at_utc`, `rotation_table_file` and
`rotation_table_sha256` (the published table's name and the manifest's digest),
`rotation_export_repository_commit` (the manifest's `repository_commit`), the manifest's
`provider`, `model_identifier`, `model_version` and `prompt_sha256`, `registry_file` and
`registry_sha256` (the registry read and the digest of its bytes), and `club_news_log_file`
(the receipt's file name).

### `checks`

Each is true in a printed record, because a false one refuses: `source_kind` (`capture`),
`checkout_at_export_commit`, `news_capture_precedes_decision_capture`,
`replay_matches_published_table` with `replay_table_sha256`, `replay_matches_manifest`,
`claims_accounted` (the identities below), `log_capture_id_matches`, `log_raw_claims_match`
and `log_outcomes_match_capture` (the four outcome lines name exactly the clubs in
`read_not_coded`).

### `hosts` and `registered_pages`

The Example FC placeholder is never contacted and is left out of every host and page count. A
host is the scheme and host of a registry URL, in lower case.

- `registered`: distinct hosts in the registry.
- `asked`: distinct hosts of the registry entries whose club is in the capture's
  `clubs_declared`. The Friday run passes no `--club`, so every registered host is asked. A
  host whose terms reading had expired is refused before contact and counts as asked and
  refused, because the capture cannot tell the two apart.
- `answered`: asked hosts from which the capture retains at least one document, by the host of
  the document's requested URL.
- `refused`: `asked` minus `answered`. `asked_hosts`, `answered_hosts` and `refused_hosts` list
  them.
- `registered_pages`: `asked`, the registry entries of declared clubs, and `read`, those whose
  URL is the requested URL of a retained document.

### `clubs`

`declared`, `covered_in_capture` and `partially_covered_in_capture` (the capture index's three
lists), `covered_in_table` (the manifest's `clubs_covered`, after the exporter has removed
clubs whose response it refused or whose every claim lost its citation), and `read_not_coded`
(clubs with a retained document and no stored response).

### `documents`

`retained`: documents in the capture (registered pages and the articles they link to).
`by_club`: the same per club. `with_verified_publication`: documents whose own held fields
state a publication time verifiably, the test the acquisition report calls a dated article.

### `responses`

- `stored`: entries of the capture's response index, one per coded club.
- `distinct`: distinct response texts; the exporter reads each distinct text once.
- `reused_from_earlier_capture`: entries that carry `reused_from_snapshot` (none is expected:
  the Friday launcher passes no earlier capture).
- `refused_whole`: distinct texts the exporter's reading refuses entirely, that is
  `locate_claims_reporting` or `parse_claim_response` raises: a format breach, a claims or
  documents list that cannot be read, or one player coded twice in one response.
  `refused_clubs` names their clubs.
- `refused_without_claims_list`: of those, the texts that hold no readable list of claims (not
  JSON, not an object, or no `claims` array).

### `acquisition_log`

Read from the receipt, which PowerShell writes with a byte order mark.

- `raw_claims_printed` from the `Raw claims    N;` line, `model_call_budget` and
  `model_calls_attempted` from the `Call budget   B; A attempted;` line, and the numbers of
  `Read refusal:` lines (`read_refusal_lines`) and `Coding refusal:` lines
  (`coding_refusal_lines`). The capture stores no call count (#1006 item 10), so
  `model_calls_attempted` comes from the receipt only.
- `call_failed_clubs`, `budget_stopped_clubs`, `refused_before_call_clubs` and
  `nothing_selected_clubs`, from the coding stage's four outcome lines, printed as
  `<label>: N [<club>, <club>]` with the labels `Call attempted and failed`,
  `Stopped by the call budget, no call attempted`, `Refused before a call was attempted` and
  `No document selected for coding`. A club the capture holds pages and no answer for is in
  exactly one of them, and no other club is in any.
- Only `call_failed_clubs` names model calls that were made. `code_week` gives a club that
  outcome when its call was attempted and did not give a usable answer: an answer refused
  after it arrived (stopped at the token ceiling, not JSON, the wrong contract, a decline)
  and a call that never answered (a timeout, a provider error) alike. The receipt's reason
  text is not read, and the capture stores neither kind.

### `claims`

Each distinct response text is followed as `_inputs_from_capture` reads it: located against
the documents of its own clubs only, then parsed.

- `raw`: the length of the `claims` array, summed over distinct texts (zero for a text with no
  readable list).
- `raw_per_coded_club`: the same summed per coded club, as the receipt's `Raw claims` line
  counts it. It equals `raw` unless two clubs' responses are byte for byte the same.
- `in_refused_responses`: claims listed in responses refused whole.
- `unverifiable_citation_own_club`: claims `locate_claims_reporting` sets aside (a quote not
  found exactly once in the cited page, a page that was not fetched, an empty field, a claim
  the parser refuses on its own, or the twin of one set aside) whose `team_name` is a club of
  the response. The exporter counts these as `claims_unverifiable_citation`, and the reporter
  checks the two agree.
- `unverifiable_citation_other_club`: the same claims when they name another club's player.
  The exporter drops these without counting them.
- `reached_join`: claims `parse_claim_response` returns; the exporter hands exactly these to
  the identity join, and the reporter checks the two agree.
- The identity join, `resolve_claim_player` against the decision capture's roster within the
  claim's club: `unknown_team` (the roster carries no such club), `no_match` (the club has no
  player of that name), `ambiguous` (two or more players match, so the claim resolves to
  nobody by rule), and `joined_to_one_player` = `reached_join` - `no_match` - `unknown_team` -
  `ambiguous`. These are #524's three counts: one player, none (`no_match` and `unknown_team`,
  kept apart) and ambiguous.
- After the join, as `_resolved_claims` records them: `other_club_source` (joined to a player
  of a club other than the cited page's), `unverified_club_source` (the cited page and digest
  belong to no retained document), `conflicting_player_claims` (claims on a player who was
  given two different statements; all of them are set aside), and `unresolved_by_reason` (the
  table's `claims_unresolved` as it stands, including any reason not named here).
- `identical_repeats`: claims equal in every recorded field to one already placed on the same
  player, which the table does not store twice. The exporter does not count them, so this is
  `reached_join` - `placed` - the sum of `unresolved_by_reason`. A repeat of a statement that a
  later contradiction sets aside stays a repeat; its statement is counted under
  `conflicting_player_claims`.
- `placed`: claims that became a player row's disposition (`claims_coded`).

The identities, checked before anything is printed (`claims_accounted`):
`raw` = `in_refused_responses` + `unverifiable_citation_own_club` +
`unverifiable_citation_other_club` + `reached_join`, and `reached_join` = `placed` +
`identical_repeats` + the sum of `unresolved_by_reason`, with `identical_repeats` not
negative.

### `table`

From the published table and its manifest: `rows`, `roster_size`, `players_with_statement`
(rows with `rotation_claim_observed`), `players_not_addressed`,
`players_with_unverifiable_citation` and `players_with_conflicting_claims` (the players the
table flags `rotation_claim_unresolved` for each reason), and `statements_by_disposition`
(rows per disposition).

### `reader`

The table read with `load_manager_words` exactly as the publish reads it: the rotation table,
the club-news capture directory as the source and the snapshot store as the root.

- `source_check`: `cited_documents_held`, or `nothing_cited` when the table cites no document.
- `statements_read`: rows with a disposition.
- `constraining_statements`: statements the rule gives a role.
- `excluded_not_starting` and `excluded_not_captain`: the sizes of the solver's two sets. A
  player kept out of the eleven is kept out of the captaincy too, so he is in both.
- `double_gameweek_reason`: statements given `ambiguous_current_week_fixture`.
- `words_withheld` and `words_unresolved`: statements whose words are withheld for figure
  wording or could not be resolved from the held page.
- `absence_or_doubt_statements`: statements with `stated_expected_absent` or
  `stated_rotation_risk`, the two dispositions the rule acts on.
- `absence_or_doubt_not_applied_by_scope`: of those, the ones with no role and no
  double-gameweek reason, counted by the table's scope label.

## The reading that decides #1006

A **statement** is one raw claim. A statement is **lost** in one of two ways.

- `lost_before_table`: it never becomes a player row's disposition:
  `in_refused_responses` + `unverifiable_citation_own_club` +
  `unverifiable_citation_other_club` + the sum of `unresolved_by_reason`. An identical repeat is
  not lost, because its statement is carried once. A claim set aside under a declared rule (an
  ambiguous name, another club's page, two statements about one player) is lost: it did not
  reach the decision, and the record names the rule beside it.
- `lost_unapplied`: it becomes a row with `stated_expected_absent` or `stated_rotation_risk`,
  the reader gives it no role and no double-gameweek reason, its scope label is neither
  `other_competition` nor `past`, and it is not a `next_match_before_target` statement. The
  two labels that show the statement names another competition or a past match are not
  counted. Nor is a statement labelled `upcoming_premier_league` on a page whose publication
  the reader verifies to an instant at or before the decision capture, when the decision
  capture's calendar, read as the reader reads it, gives the club one dated target-gameweek
  fixture kicking off after the capture, no other club fixture at the same kickoff and no
  undated fixture that may come before it, and shows the club's first dated league fixture
  after that instant kicking off before the target fixture: its words name a match that is
  not the decision's, as `past` does
  (`next_match_before_target`, defined exactly below). A statement the reader gives the
  double-gameweek reason `ambiguous_current_week_fixture` is not counted either: for a club
  with two fixtures in the gameweek the rule declares the role undecidable, so its absence of
  role is the rule's own declaration, not a loss, and `double_gameweek_reason` counts it.
  Other dispositions are not counted either: the rule gives them no role by its own
  declaration.

A statement on a page whose publication time the rule cannot use, a hedge, a statement naming
a day ("Saturday's Premier League match") and one naming the player by his full name all end
in `lost_unapplied`, unless it is a `next_match_before_target` statement. Of these only the
full-name statement can be one, because it keeps the label `upcoming_premier_league`; the
others never carry that label on a page dated to a verified instant. They stay losses
whatever the cause, as a claim set aside under a declared rule does above, and the record
names the cause beside them. `lost_unapplied_by_cause` counts each under the first condition
of the rule's role that it fails, tested in this order, so the four counts add up to
`lost_unapplied`. One test that is not a cause sits between the second cause and the third:
a statement it names leaves the count there and is no loss.

- `publication_unverified`: the reader does not verify the page's publication time (the page
  states none, as undated listing pages do, or the stated time does not recheck);
- `publication_day_precision`: the page's publication is verified to the day only;
- `next_match_before_target`, not a cause: the scope label is `upcoming_premier_league`; the
  verified publication instant is at or before the decision capture; and the decision
  capture's calendar, read as the reader reads it, gives the club exactly one fixture in the
  target gameweek, dated and kicking off after the capture, no other club fixture at the same
  kickoff and no undated fixture that may come before it (one in no gameweek or in a gameweek
  up to the target), and the club's first dated league fixture after the publication instant
  kicks off before that target fixture. The earlier match may kick off before or after the
  capture. Both calendar questions are put to the rule's own binding
  (`claim_targets_next_fixture`, which takes the club's first dated fixture after
  publication): asked at the last second before the target kickoff, with the cutoff there
  too, it binds exactly when the club has one dated target-gameweek fixture, no other club
  fixture at the same kickoff and no undated fixture that may come before it; the target
  kickoff and the publication instant are compared with the capture directly; asked as the
  reader asked it, at the statement's own instant with the capture as the cutoff, it does not
  bind the statement. A blank or double target week, an undated club fixture that may come
  before the target, another club fixture at the target kickoff, a target fixture that kicked
  off by the capture and a page published after the capture do not qualify: a statement on
  such a calendar or page is not named here and stays a loss under the next cause;
- `scope_unverified`: the page is dated to the instant, the statement is not a
  `next_match_before_target` one, and the scope is not verified (a hedge, a day name, a full
  name, a wording the scope rule does not read, a next match the calendar cannot bind, or no
  single next match in the gameweek: a blank week, or a double week whose statement the
  reader does not give `ambiguous_current_week_fixture` because it fails one of that
  reason's own conditions). `lost_unapplied_scope_unverified_by_scope` counts these
  by the table's scope label. Within it the labels `unspecified` and `ambiguous` are each
  shared by several of those cases and cannot tell them apart, which is what item 3 is about;
- `publication_not_before_fetch`: publication and scope are both verified at instant
  precision and the rule still gives no role, which it does only for a page with no fetch
  instant or one stating a publication instant after its fetch.

Publication is tested first because the exporter verifies a next-match scope only from an
instant publication time, so a page without one never verifies its scope either. The order
keeps `scope_unverified`, where items 3 and 7 act, to pages dated to the instant. A loss under
`publication_unverified` or `publication_day_precision` is one that items 3 and 7 do not
address; it still counts toward the verdict, because the owner's rule routes the items on any
loss and does not ask which item would have prevented it, and the record's Markdown says so
when such a loss is counted. `next_match_before_target` is tested after the two publication
causes because it needs the publication instant, and before `scope_unverified` so that a
statement whose words name an earlier club match never reaches the cause where items 3 and 7
act: neither would change it, since item 7's acceptance already requires no club match
between publication and the target kickoff.

`excluded_from_lost_unapplied` counts the absence or doubt statements given no role and no
double-gameweek reason that are not in `lost_unapplied`, by reason: `other_competition`,
`past` and `next_match_before_target`, each named even when it is zero. With `lost_unapplied`
they add up to the statements `absence_or_doubt_not_applied_by_scope` counts.

`lost` = `lost_before_table` + `lost_unapplied`. Two further counts name answers whose
statements, if they hold any, cannot be counted at all:

- `responses_without_claims_list`: stored responses refused whole that hold no readable list
  of claims (`refused_without_claims_list`);
- `calls_attempted_and_failed`: the clubs in `call_failed_clubs`. Whatever the model answered
  for such a club, if it answered, was dropped before any capture.

A failed call is read as a loss, the same way as a stored response without a readable list of
claims: in both the model was asked and what it said cannot be counted, and they differ only
in whether the answer was refused before or after it was stored. That is item 4 (the record
cannot show what happened to every statement the model returned) and item 10 (the capture
stores no call counts). A call that never answered cannot be told apart from one whose answer
was refused, so both are read alike. A club stopped by the call budget, refused before its
call, or with no document selected had no call, so no statement of it existed to lose; it is
named in `acquisition_log` and does not enter the verdict.

The record's `loss` section carries `lost_before_table`, `lost_unapplied`,
`lost_unapplied_by_cause`, `excluded_from_lost_unapplied`,
`lost_unapplied_scope_unverified_by_scope`, `lost`, `responses_without_claims_list` and
`calls_attempted_and_failed`, with its `verdict` and `issue_1006`, which are:

| `verdict` | When | `issue_1006` | What follows |
| --- | --- | --- | --- |
| `no_raw_claims` | `raw` is 0, `responses_without_claims_list` is 0 and `calls_attempted_and_failed` is 0 | `unanswered` | No statement existed to lose, so the record cannot answer the question, as on 21 October. #1006 neither closes nor moves on this record; it stays open and the next step is the owner's. |
| `no_statement_lost` | `raw` is at least 1, `lost` is 0, `responses_without_claims_list` is 0 and `calls_attempted_and_failed` is 0 | `close` | #1006 closes, by the owner's decision of 19 October. |
| `statements_lost` | `lost` is at least 1, or `responses_without_claims_list` is at least 1, or `calls_attempted_and_failed` is at least 1 | `route_items_3_7_4_10` | Items 3, 7, 4 and 10 of #1006 go to İbrahim. The record says how many statements were lost in each place and for what cause, and which clubs' calls failed; it does not rank the items. |

There is no threshold: one lost statement, one response without a readable list of claims or
one failed call routes the items. The reading is made once, from the one record of the GW8
decision run, and is not repeated with another capture.

It decides nothing else: not whether stated news predicts who plays, not whether any count is
good or bad, not a change to the coding contract or the artifact contract, and not #1140's live
acceptance.

## What the record means for #524

The owner's condition is a real-capture Friday run with club news on, plus this record. The
record shows the run's part through its checks: `source_kind` is `capture`, the news capture
precedes the decision capture, and the rebuilt table matches the published one. Whatever the
verdict, `no_raw_claims` included, the record then exists; whether #524 closes stays the
owner's call.

If no GW8 club-news capture exists (the acquisition refused and the launcher stopped before
the weekly decision), or no rotation pair was exported from it, there is no record. The
receipt's `Refused:` line is posted on #524 instead, the reporter is not run, and neither issue
moves under this protocol.

## Where the record lands

- `docs/research/club_news_join_counts_gw8.json`: the reporter's output, byte for byte.
- `docs/research/club_news_join_counts_gw8.md`: the inputs, the counts, the verdict and what
  follows from it, in the terms of this protocol and nothing beyond them.
- A row in `docs/measurements_index.md` naming both, and this protocol's line in
  `docs/research/README.md` pointed at the record.

They arrive in one pull request after the GW8 publish, outside any run window. It changes no
code. The record carries counts, ids, club names and digests only: no quote, no paraphrase and
no player name, nothing the evidence table itself does not carry.

## What may not change after the data exists

The inputs, every count's definition, the identities, the definition of a lost statement and
the verdict table above. A count found to be missing after the data exists is added in the
record's Markdown as an addition made after the data, and does not enter the verdict.

## Checked before this was frozen

The reporter, `scripts/report_club_news_join_counts.py`, was run only on synthetic captures
written and exported by the real code, in its unit tests, with receipts whose coding stage is
printed by the acquisition's own formatter. They include a failed call beside a clean answer
and beside an empty one, a club stopped by the budget, statements not applied for each cause,
and a replay whose counts differ from the manifest while its rows do not. No real capture was
read: none is on the machine this was written on.

The amendment of 2026-10-22 was checked the same way, on synthetic captures with calendars
changed where a case needs it: a next-match statement on a page published before its club's
previous match, left out by name on an otherwise clean week, and the same page published after
that match, applied; the same statement left out when a rearranged club match kicks off
between the capture and the target, with the page published before or after the club's
previous match, and when it names the player in full; the same statement on a page dated to
the day or not at all, on a page whose stated instant does not recheck, with another label,
on an undated, blank or double target week, beside an undated fixture and a club match after
the capture, on a target fixture that kicked off by the capture, and on a page published
after the capture, and a statement the scope rule does not verify, with no intervening match
(once naming the player in full), each still lost under its own cause; a double-gameweek
statement given `ambiguous_current_week_fixture`;
an `other_competition` and a `past` statement beside a clean week; a receipt whose outcome
line miscounts its clubs; and a run whose `squadopt` is imported from another checkout. Still
no real capture was read.
