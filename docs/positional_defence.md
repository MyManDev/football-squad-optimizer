# A positional structure for goalkeepers and defenders

Contract `positional_defence_v1`. Protocol: `docs/positional_defence_prereg.md`. Verdict: **`fails`**.

Population: 31737 goalkeeper and defender rows over the judged seasons' decisions from target gameweek 4, 11725 of them appearances. Before the drop rules there were 33235 rows and 12270 appearances; 219 `direct_control` rows, 1289 double-gameweek rows and 0 blank-gameweek rows were removed, 10 of them by more than one rule.

## Clause 1: accuracy

Binding, on appeared rows: mean improvement -0.06794371230580248, interval [-0.0784540564931899, -0.05789292330687874], improves every judged season False. Passes: **False**.

Floor, over the 31737 surviving rows: candidate 0.985882828343237 against control 0.9677398289755491. Passes: **False**.

## Clause 2: ordering

Within-position Spearman on appeared rows, tolerance 0.01. Passes: **True**.

## Clause 3: decisions

104 paired decisions, mean difference -0.5192307692307693, losing seasons ['2022-23', '2024-25']. Passes: **False**. The interval [-1.7600961538461541, 0.8846153846153846] is reported and does not gate.

## What else was running

Other sessions share this machine. Both solver limits are deterministic, so no measured number moves under that load; `elapsed_seconds` does, and is not a quiet-machine timing.

