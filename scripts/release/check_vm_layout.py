"""Refuse the ordinary VM sync when Compose selects a separately retained release."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

ROOTS = {
    "site": "SQUADOPT_BACKEND_SITE_DATA_ROOT",
    "snapshots": "SQUADOPT_BACKEND_SNAPSHOT_ROOT",
    "handoffs": "SQUADOPT_BACKEND_HANDOFF_ROOT",
    "artifacts": "SQUADOPT_BACKEND_ARTIFACT_ROOT",
}
SERVICES = ("api", "worker")


def check_layout(config: dict[str, Any], containers: list[dict[str, Any]], base: Path) -> None:
    """Check configured and running mounts without exposing their environment values."""
    if set(config["services"]) != set(SERVICES):
        raise ValueError("VM sync requires exactly the API and worker services.")
    expected = {f"/mnt/{name}": str(base / name) for name in ROOTS}
    for name in ROOTS:
        if (base / name).is_symlink() or not (base / name).is_dir():
            raise ValueError("VM sync requires ordinary existing data directories, not symlinks.")
    running: dict[str, dict[str, Any]] = {}
    for container in containers:
        service = container["Config"]["Labels"]["com.docker.compose.service"]
        if service not in SERVICES or service in running:
            raise ValueError("VM sync requires exactly one API and one worker container.")
        running[service] = container
    if set(running) != set(SERVICES):
        raise ValueError("VM sync requires both existing backend containers.")
    for service in SERVICES:
        declared = config["services"][service]
        observed = running[service]
        for configured, mounts in (
            (True, declared["volumes"]),
            (False, observed["Mounts"]),
        ):
            for target, source in expected.items():
                selected = [
                    mount
                    for mount in mounts
                    if mount.get("target" if configured else "Destination") == target
                ]
                if len(selected) != 1:
                    raise ValueError(f"VM sync requires one {target} bind in both services.")
                mount = selected[0]
                if (
                    mount.get("type" if configured else "Type") != "bind"
                    or mount.get("source" if configured else "Source") != source
                    or (mount.get("read_only") if configured else mount.get("RW") is False)
                    is not True
                ):
                    raise ValueError(
                        "VM sync refused: a selected data mount differs from its ordinary "
                        "transfer destination. Prepare and validate a complete release package, "
                        "then explicitly activate that package; preserve the current selection."
                    )
        configured_env = declared["environment"]
        observed_env = dict(item.split("=", 1) for item in observed["Config"]["Env"])
        for name, variable in ROOTS.items():
            target = f"/mnt/{name}"
            if configured_env.get(variable) != target or observed_env.get(variable) != target:
                raise ValueError("VM sync refused: a runtime data root differs from its mount.")


def _docker_json(arguments: list[str]) -> Any:
    result = subprocess.run(
        ["docker", *arguments], capture_output=True, text=True, timeout=30, check=False
    )
    if result.returncode:
        raise ValueError("Could not inspect the VM layout; no sync is permitted.")
    return json.loads(result.stdout)


def main() -> int:
    base = Path.home() / "squadopt"
    try:
        config = _docker_json(
            [
                "compose",
                "--project-directory",
                str(base / "repo"),
                "--env-file",
                str(base / ".env"),
                "-f",
                str(base / "repo/deploy/compose.yaml"),
                "-f",
                str(base / "compose.artifacts.yaml"),
                "config",
                "--format",
                "json",
            ]
        )
        containers = _docker_json(["inspect", "squadopt-api-1", "squadopt-worker-1"])
        check_layout(config, containers, base)
    except ValueError as error:
        if isinstance(error, json.JSONDecodeError):
            print("Could not read the VM layout; no sync is permitted.")
        else:
            print(str(error))
        return 1
    except (OSError, KeyError, TypeError, subprocess.SubprocessError):
        print("Could not verify the VM layout; no sync is permitted.")
        return 1
    print("VM configured and running data roots match the ordinary sync destinations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
