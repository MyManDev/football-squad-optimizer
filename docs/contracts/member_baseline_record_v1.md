# Member baseline record

`member_baseline_record_v1` records the server's unweighted one-week `saf-puan` answer for an FPL entry. Its key is season, gameweek, entry and capture. Neither the record nor its advice digest contains a league, so the same entry can use one record in several tracked leagues.

The record contains the capture identity and time, source `server_one_week_baseline`, the member's held squad and transfer state, projection and planner provenance, the player join map, and one scoring-complete advice document. The advice freezes the starters, ordered bench, captain, vice-captain, transfers, hit charge and expected own points. Its digest describes the computed payload with the page's league identifier removed.

This record makes no claim about a published page address or exact page bytes. It carries no `told`, `published_path` or `published_sha256`. A history writer must still prove that the relevant member page used this capture before the deadline, using the existing published-capture map. A record alone does not prove publication or adoption.

Storage retains the existing create-once and replay rules. A later capture has its own directory; a second write to the same key must reproduce the recorded decision. The manifest identifies this contract. Legacy `member_advice_record_v2` publication records remain readable with their original league identity and are never rewritten as baselines.

The record builder and settled reader support this contract. The weekly run must supply the server baseline once per distinct entry and capture when it adopts the new record path; page output is not an input to this builder.
