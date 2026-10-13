# Integration tests

End-to-end tests that cross packages, processes or languages. `tests/conftest.py` marks every
test in this folder `integration`. Most of them run in the normal suite, on synthetic inputs and
without internet access; the model-coded news chains use a synthetic model name and a
placeholder key, and call no model.

## Opt-in probes

Four files skip unless an environment variable is set to `1`, because they need something the
normal suite does not have.

| Test | Switch | What it needs and proves | Run by |
| --- | --- | --- | --- |
| `test_publication_contract.py` | `SQUADOPT_PUBLICATION_CONTRACT=1` | Node: the offline Python publisher's output read by the real TypeScript consumer, index addresses included | CI job `web (node 22)`, step `Python publication and browser API worker acceptance` |
| `test_advice_browser.py` | `SQUADOPT_BROWSER_SMOKE=1` | Chromium and a built site: the production API factory and a separate worker over a temporary store, driven from the browser with no mocked response | The same CI step; locally as the [web guide](../../web/README.md#browser-check-with-the-real-advice-backend) describes |
| `test_backend_container.py` | `SQUADOPT_CONTAINER_SMOKE=1`, with `SQUADOPT_CONTAINER_IMAGE` naming the image | A built backend image: the API and the worker as containers | CI job `container (linux/amd64)`, step `Container smoke` |
| `test_advice_capacity.py` | `SQUADOPT_CAPACITY_PROBE=1`, with `SQUADOPT_CAPACITY_SCENARIOS` to choose the burst shapes | The local machine's resources: synthetic real-solver bursts against the API and workers | No CI job; run by hand as [advice capacity](../../docs/architecture/advice_capacity.md) describes |

The CI web step sets both of its switches and runs:

```sh
python -m pytest tests/integration/test_publication_contract.py tests/integration/test_advice_browser.py -q
```

## The other files

| Group | Files |
| --- | --- |
| Optimization and evaluation chains | `test_end_to_end.py`, `test_csv_integration.py`, `test_evaluation_integration.py`, `test_walk_forward_evaluation.py` |
| Advice backend in process and across processes | `test_backend_api.py`, `test_backend_two_process.py` |
| Backup and restore | `test_backup_domain_restore.py` |
| Decision chains and publication | `test_component_decision_chain.py`, `test_decision_chain_rehearsal.py`, `test_football_component_publication.py` |
| Club news and model-coded news | `test_club_news_evidence_chain.py`, `test_club_news_rehearsal.py`, `test_current_football_news_planner_chain.py`, `test_fpl_news_decision_flow.py`, `test_openai_news_minute_chain.py` |
| Football experiments | `test_football_flag_experiment.py`, `test_football_load_experiment.py`, `test_football_phase_experiment.py`, `test_football_score_state_experiment.py`, `test_football_tactical_experiment.py` |

A new opt-in probe skips unless its own `SQUADOPT_<NAME>=1` variable is set, and gets a row in
the table above.
