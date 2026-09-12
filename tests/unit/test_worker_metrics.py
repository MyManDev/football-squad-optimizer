"""Scrapes observe one worker, without combining it with API counters."""

from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from squadopt.platform.advice_observability import AdviceMetrics
from squadopt.platform.worker_metrics import serve_worker_metrics


def test_metrics_listener_is_independent_and_releases_its_socket() -> None:
    worker, api = AdviceMetrics(), AdviceMetrics()
    worker.solve_seconds(1.25)
    worker.increment("advice_jobs_total", outcome="completed")
    api.cache_hit()
    with serve_worker_metrics(lambda: worker.render(queue_depth=2), port=0) as server:
        address = f"http://127.0.0.1:{server.server_port}"
        with urlopen(f"{address}/metrics", timeout=2) as response:
            text = response.read().decode()
        assert 'advice_jobs_total{outcome="completed"} 1' in text
        assert "advice_solve_seconds_count 1" in text
        assert "advice_cache_hits_total" not in text
        with urlopen(f"{address}/health", timeout=2) as response:
            assert response.status == 200
        with pytest.raises(HTTPError) as error:
            urlopen(f"{address}/anything", timeout=2)
        assert error.value.code == 404
    assert server.socket.fileno() == -1


def test_concurrent_scrapes_do_not_race_with_metric_updates() -> None:
    metrics = AdviceMetrics()

    def write() -> None:
        for _ in range(1000):
            metrics.increment("test_counter")
            metrics.observe("test_seconds", 0.5)

    def scrape() -> None:
        for _ in range(300):
            assert isinstance(metrics.render(), str)

    with ThreadPoolExecutor(max_workers=4) as pool:
        for result in [
            pool.submit(write),
            pool.submit(write),
            pool.submit(scrape),
            pool.submit(scrape),
        ]:
            result.result()
    rendered = metrics.render()
    assert "test_counter 2000" in rendered
    assert "test_seconds_count 2000" in rendered
