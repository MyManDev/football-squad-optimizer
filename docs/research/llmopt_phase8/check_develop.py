"""Run the original develop worker and intent tests against this checkout's code."""

import io
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEVELOP = "177000ec2cfcd0eb525f9253cd46afd75b7ac733"
TESTS = (
    "tests/unit/test_advice_worker.py",
    "tests/unit/test_live_football_model.py",
    "tests/unit/test_observed_football_worker.py",
    "tests/unit/test_llmopt_intent.py",
)


def main():
    # Keep the tests' own cross-imports and shared fixture defaults at the same revision.
    archive = subprocess.check_output(
        [
            "git",
            "archive",
            "--format=zip",
            DEVELOP,
            "tests",
            "pyproject.toml",
            "web/src/fixtures/league.ts",
        ],
        cwd=ROOT,
    )
    with tempfile.TemporaryDirectory(prefix="llmopt-off-") as directory:
        tree = Path(directory)
        with zipfile.ZipFile(io.BytesIO(archive)) as original:
            original.extractall(tree)
        environment = {
            **os.environ,
            "PYTHONPATH": os.pathsep.join(map(str, (tree, ROOT / "src", ROOT))),
            "SQUADOPT_BACKEND_LLMOPT_VNEXT": "0",
        }
        print(f"Running develop tests from {DEVELOP} against {ROOT / 'src'}", flush=True)
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *TESTS],
            cwd=tree,
            env=environment,
            check=False,
        ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
