# Member advice baseline

This fixture pins five current product outputs from the synthetic window world.
List ordering is pinned exactly; the test does not define a policy for tie-breaking.
Floating values use an absolute tolerance of 1e-12 and no relative tolerance.

To verify the pin, with the repository environment active and `PYTHONPATH=src`:

```text
python -m pytest tests/unit/test_member_windows.py::test_existing_five_plans_keep_their_recorded_results
```

Regeneration is a deliberate replacement of the reference, not a verification step.
From the repository root in PowerShell, the following command rebuilds it using only
synthetic inputs. Review every difference before retaining the generated file.

```powershell
$env:PYTHONPATH = 'src'
@'
import dataclasses
import json
import tempfile
from pathlib import Path
from tests.unit.test_member_windows import ENTRY, SEASON, _advise, _window_world

path = Path('tests/fixtures/member_advice_baseline.json')
keys = json.loads(path.read_text(encoding='utf-8'))
with tempfile.TemporaryDirectory() as temporary:
    world = _window_world.__wrapped__(Path(temporary))
    picks = world['provider'].picks(ENTRY, SEASON, 1)
    world['provider']._picks[202] = dataclasses.replace(picks, entry_id=202)
    result = {}
    for key in keys:
        strategy, window = key.split('/')
        payload = _advise(world, strategy=strategy, window=int(window),
                          rival_entry_id=None if strategy == 'saf-puan' else 202)
        payload.pop('source_snapshot_id', None)
        result[key] = payload
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + chr(10),
                    encoding='utf-8', newline=chr(10))
'@ | python -
```

