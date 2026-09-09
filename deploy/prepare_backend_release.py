"""Prepare an inspectable backend release without authenticating, pushing or deploying."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

FIELDS = {
    "resource_group",
    "app_name",
    "location",
    "environment_id",
    "image",
    "registry_identity_id",
    "allowed_origins",
    "operation",
}
RESOURCE = (
    r"/subscriptions/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/resourceGroups/[\w.()-]+/providers/"
)
IMAGE = re.compile(r"[a-z0-9][a-z0-9.-]*\.azurecr\.io/[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}")
CONTAINER_TESTS = sorted(
    "tests/integration/test_backend_container.py::" + name
    for name in (
        "test_the_image_is_the_measured_environment_on_the_measured_architecture",
        "test_a_worker_without_its_volume_refuses_to_start",
        "test_two_containers_from_one_image_answer_through_the_shared_volume",
    )
)


def encoded(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_config(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - FIELDS:
        raise ValueError("Configuration must be an object containing only documented fields.")
    if FIELDS - {"operation"} - set(value):
        raise ValueError("Configuration is missing required fields.")
    config = dict(value)
    for key in FIELDS - {"allowed_origins", "operation"}:
        if (
            not isinstance(config[key], str)
            or not config[key]
            or config[key] != config[key].strip()
        ):
            raise ValueError(f"{key} must be a nonempty trimmed string.")
    patterns = {
        "resource_group": r"[A-Za-z0-9_][A-Za-z0-9_.()-]{0,89}",
        "app_name": r"[a-z][a-z0-9-]{0,30}[a-z0-9]",
        "location": r"[a-z][a-z0-9]+",
        "environment_id": RESOURCE + r"Microsoft\.App/managedEnvironments/[\w-]+",
        "registry_identity_id": RESOURCE
        + r"Microsoft\.ManagedIdentity/userAssignedIdentities/[\w-]+",
    }
    for key, pattern in patterns.items():
        if not re.fullmatch(pattern, config[key]) or (key == "app_name" and "--" in config[key]):
            raise ValueError(f"Invalid {key}.")
    if not IMAGE.fullmatch(config["image"]):
        raise ValueError("image must be an ACR repository pinned by a lowercase SHA256 digest.")
    repository = config["image"].split("/", 1)[1].split("@", 1)[0]
    if any(part in ("", ".", "..") for part in repository.split("/")):
        raise ValueError("Invalid image repository path.")
    operation = config.setdefault("operation", "create")
    if operation not in ("create", "update"):
        raise ValueError("operation must be create or update.")
    origins = config["allowed_origins"]
    if not isinstance(origins, list) or not origins:
        raise ValueError("allowed_origins must be a nonempty list.")
    for origin in origins:
        if not isinstance(origin, str) or not re.fullmatch(
            r"https://[A-Za-z0-9.-]+(?::[0-9]+)?", origin
        ):
            raise ValueError(
                "Each allowed origin must be an HTTPS origin, without a path or wildcard."
            )
        parsed = urlsplit(origin)
        if not parsed.hostname or parsed.port == 0:
            raise ValueError("Invalid origin host or port.")
        if any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            for label in parsed.hostname.split(".")
        ):
            raise ValueError("Invalid origin hostname.")
    if len(set(origins)) != len(origins):
        raise ValueError("Duplicate allowed origins.")
    config["allowed_origins"] = sorted(origins)
    return config


def command(arguments: list[str], root: Path) -> str:
    result = subprocess.run(arguments, cwd=root, capture_output=True, text=True, check=False)
    if result.returncode:
        raise ValueError(f"Command failed ({result.returncode}): {arguments[0]}")
    return result.stdout.strip()


def source_receipt(root: Path) -> dict[str, Any]:
    git = ["git", "--no-optional-locks", "-C", str(root)]
    if Path(command([*git, "rev-parse", "--show-toplevel"], root)).resolve() != root:
        raise ValueError("source-root must be the worktree root.")
    if command([*git, "status", "--porcelain=v1", "--untracked-files=all"], root):
        raise ValueError("Source checkout must be clean before release preparation.")
    fixed = ["Dockerfile", ".dockerignore", "pyproject.toml", "README.md", "constraints.txt"]
    tracked = set(command([*git, "ls-files", "--", *fixed, "src"], root).splitlines())
    paths = [root / name for name in fixed]
    for path in (root / "src").rglob("*"):
        if "__pycache__" in path.parts or re.search(r"\.py[codz]$", path.name):
            continue
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise ValueError("Build inputs may not contain filesystem links.")
        if path.is_file():
            paths.append(path)
    hashes = {}
    for path in paths:
        if path.is_symlink():
            raise ValueError("Build inputs may not contain filesystem links.")
        relative = path.resolve().relative_to(root).as_posix()
        if relative not in tracked:
            raise ValueError("Build input exists outside the recorded Git tree.")
        hashes[relative] = sha256(path)
    return {
        "commit": command([*git, "rev-parse", "HEAD"], root),
        "tree": command([*git, "rev-parse", "HEAD^{tree}"], root),
        "build_inputs": hashes,
        "build_inputs_sha256": hashlib.sha256(encoded(hashes).encode()).hexdigest(),
    }


def render(template: object, values: dict[str, str]) -> object:
    if isinstance(template, dict):
        return {str(render(key, values)): render(value, values) for key, value in template.items()}
    if isinstance(template, list):
        return [render(value, values) for value in template]
    if isinstance(template, str) and ("<" in template or ">" in template):
        if template not in values:
            raise ValueError("Template contains an unknown or partial placeholder.")
        return values[template]
    return template


def validate_image_inspection(image: dict[str, Any], commit: str) -> str:
    environment = dict(item.split("=", 1) for item in image["Config"]["Env"] if "=" in item)
    label = image["Config"].get("Labels", {}).get("org.opencontainers.image.revision")
    if image["Architecture"] != "amd64" or image["Os"] != "linux":
        raise ValueError("Built image must be linux/amd64.")
    if label != commit or environment.get("SQUADOPT_REPOSITORY_COMMIT") != commit:
        raise ValueError("Built image stamp does not match the clean source checkout.")
    image_id = str(image["Id"])
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise ValueError("Docker did not return an immutable image ID.")
    return image_id


def logged(arguments: list[str], root: Path, output: Path, env: dict[str, str]) -> None:
    with output.open("w", encoding="utf-8") as stream:
        result = subprocess.run(
            arguments,
            cwd=root,
            env=env,
            stdout=stream,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=1800,
        )
    if result.returncode:
        raise ValueError(f"Local verification failed; see {output}.")


def validate_container_junit(path: Path) -> list[str]:
    report = ET.parse(path)
    cases = list(report.iter("testcase"))
    if any(case.find(tag) is not None for case in cases for tag in ("skipped", "failure", "error")):
        raise ValueError("A failed or skipped suite is not container evidence.")
    nodeids = sorted(
        case.get("classname", "").replace(".", "/") + ".py::" + case.get("name", "")
        for case in cases
    )
    if nodeids != CONTAINER_TESTS or any(
        int(suite.get(key, "0")) != 0
        for suite in report.iter("testsuite")
        for key in ("errors", "failures", "skipped")
    ):
        raise ValueError("All three mandatory container node IDs must pass exactly once.")
    return nodeids


def verification_record(
    source: dict[str, Any], image: dict[str, Any], junit: Path, inspection: Path
) -> dict[str, Any]:
    return {
        "status": "passed",
        "image_id": validate_image_inspection(image, source["commit"]),
        "tested_commit": source["commit"],
        "tested_source": source,
        "test_nodeids": validate_container_junit(junit),
        "junit_sha256": sha256(junit),
        "image_inspection_sha256": sha256(inspection),
        "registry_availability_verified": False,
    }


def reuse_verified(receipt_path: Path, output: Path) -> dict[str, Any]:
    previous = json.loads(receipt_path.read_text(encoding="utf-8"))
    proof = previous["container_verification"]
    if previous["schema"] != "backend_release_preparation_v1" or proof["status"] != "passed":
        raise ValueError("The previous receipt must contain passed local container evidence.")
    junit = receipt_path.parent / "container-smoke.xml"
    inspection = receipt_path.parent / "image-inspection.json"
    for path, key in ((junit, "junit_sha256"), (inspection, "image_inspection_sha256")):
        if key in proof and sha256(path) != proof[key]:
            raise ValueError("Retained verification evidence changed.")
    tested_source = proof.get("tested_source", previous["source"])
    image = json.loads(inspection.read_text(encoding="utf-8"))
    result = verification_record(tested_source, image, junit, inspection)
    if proof["image_id"] != result["image_id"] or (
        "tested_commit" in proof and proof["tested_commit"] != result["tested_commit"]
    ):
        raise ValueError("Retained image evidence differs from the receipt.")
    for path in (junit, inspection):
        shutil.copyfile(path, output / path.name)
    result["reused_receipt_sha256"] = sha256(receipt_path)
    result["temporary_environment"] = proof.get("temporary_environment", "not_recorded")
    return result


def verify_container(
    root: Path, output: Path, source: dict[str, Any], reference: str
) -> dict[str, Any]:
    env = dict(os.environ)
    for key in tuple(env):
        if key.startswith("PYTEST_"):
            del env[key]
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    temporary = output / "tmp"
    temporary.mkdir()
    env["TMP"] = env["TEMP"] = env["TMPDIR"] = str(temporary)
    iidfile = output / "image.id"
    logged(
        [
            "docker",
            "build",
            "--platform",
            "linux/amd64",
            "--build-arg",
            f"SQUADOPT_REPOSITORY_COMMIT={source['commit']}",
            "--iidfile",
            str(iidfile),
            str(root),
        ],
        root,
        output / "docker-build.log",
        env,
    )
    image = json.loads(command(["docker", "image", "inspect", iidfile.read_text().strip()], root))[
        0
    ]
    image_id = validate_image_inspection(image, source["commit"])
    (output / "image-inspection.json").write_text(encoded(image), encoding="utf-8")
    env.update(
        {
            "SQUADOPT_CONTAINER_SMOKE": "1",
            "SQUADOPT_CONTAINER_IMAGE": image_id,
            "PYTHONPATH": os.pathsep.join((str(root / "src"), str(root))),
        }
    )
    junit = output / "container-smoke.xml"
    basetemp = root / ".pt" / ("d4ct-" + uuid4().hex[:6])
    logged(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/integration/test_backend_container.py",
            "-q",
            "-p",
            "no:cacheprovider",
            "-o",
            "addopts=",
            f"--basetemp={basetemp}",
            f"--junitxml={junit}",
        ],
        root,
        output / "container-smoke.log",
        env,
    )
    result = verification_record(source, image, junit, output / "image-inspection.json")
    if source_receipt(root) != source:
        raise ValueError("Source checkout changed during the local image verification.")
    result["temporary_environment"] = {key: env[key] for key in ("TMP", "TEMP", "TMPDIR")}
    return result


APPLY = """param([switch]$PreflightOnly)
$ErrorActionPreference = 'Stop'
$receipt = Join-Path $PSScriptRoot 'release.json'
$receiptHash = (Get-FileHash -LiteralPath $receipt -Algorithm SHA256).Hash.ToLowerInvariant()
if ($receiptHash -cne '<RECEIPT_HASH>') {
    throw 'The receipt changed; prepare and review the release again.'
}
$release = Get-Content -LiteralPath $receipt -Raw | ConvertFrom-Json
$yaml = Join-Path $PSScriptRoot 'containerapp.yaml'
$actualHash = (Get-FileHash -LiteralPath $yaml -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualHash -cne $release.yaml_sha256) {
    throw 'The prepared YAML changed; prepare and review the release again.'
}
$proof = $release.container_verification
if ($proof.status -cne 'passed') { throw 'Passed local container evidence is required.' }
$raw = & docker image inspect $release.config.image
if ($LASTEXITCODE -ne 0) {
    throw 'The exact registry digest must already be present locally; no pull was attempted.'
}
$images = @($raw | ConvertFrom-Json)
if ($images.Count -ne 1) { throw 'Docker must return exactly one image.' }
$image = $images[0]
if ($image.Id -cne $proof.image_id -or $image.Os -cne 'linux' -or
    $image.Architecture -cne 'amd64') {
    throw 'The registry reference does not identify the tested linux/amd64 image.'
}
if (@($image.RepoDigests) -cnotcontains $release.config.image) {
    throw 'Docker metadata must include the exact repository digest.'
}
$stamps = @($image.Config.Env | Where-Object { $_ -clike 'SQUADOPT_REPOSITORY_COMMIT=*' })
$expectedStamp = 'SQUADOPT_REPOSITORY_COMMIT=' + $proof.tested_commit
if ($stamps.Count -ne 1 -or $stamps[0] -cne $expectedStamp -or
    $image.Config.Labels.'org.opencontainers.image.revision' -cne $proof.tested_commit) {
    throw 'The registry image stamp differs from the tested commit.'
}
if ($PreflightOnly) {
    Write-Output 'Local image association verified; no Azure command ran.'
    return
}
$arguments = @($release.apply_arguments) + @('--yaml', $yaml)
& az @arguments
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
"""


def prepare(
    root: Path,
    config_path: Path,
    template_path: Path,
    output: Path,
    verify: bool,
    verified_receipt: Path | None = None,
) -> Path:
    if verify and verified_receipt is not None:
        raise ValueError("Choose fresh verification or a retained receipt, not both.")
    root = root.resolve()
    scratch = root / ".pt"
    scratch.resolve().relative_to(root)
    output = output.resolve()
    if output == scratch.resolve() or not output.is_relative_to(scratch.resolve()):
        raise ValueError("Output must be a new directory below source-root/.pt.")
    if output.exists():
        raise ValueError("Output already exists; choose a new release directory.")
    config = validate_config(json.loads(config_path.read_text(encoding="utf-8")))
    source = source_receipt(root)
    values = {
        "<APP_NAME>": config["app_name"],
        "<LOCATION>": config["location"],
        "<ENVIRONMENT_ID>": config["environment_id"],
        "<IMAGE>": config["image"],
        "<REGISTRY>": config["image"].split("/", 1)[0],
        "<PULL_IDENTITY>": config["registry_identity_id"],
        "<ORIGINS>": ",".join(config["allowed_origins"]),
    }
    manifest = render(json.loads(template_path.read_text(encoding="utf-8")), values)
    output.mkdir(parents=True)
    yaml = output / "containerapp.yaml"
    yaml.write_text(encoded(manifest), encoding="utf-8")
    receipt: dict[str, Any] = {
        "schema": "backend_release_preparation_v1",
        "created_utc": datetime.now(UTC).isoformat(),
        "source": source,
        "config": config,
        "template_sha256": sha256(template_path),
        "yaml_sha256": sha256(yaml),
        "image_reference_origin": "operator_supplied",
        "container_verification": {"status": "not_requested"},
        "cloud_deployment": "not_run",
        "cloud_mount_acceptance": "not_run",
        "public_ingress": "disabled",
        "apply_arguments": [
            "containerapp",
            config["operation"],
            "--resource-group",
            config["resource_group"],
            "--name",
            config["app_name"],
        ],
    }
    if verify:
        receipt["container_verification"] = verify_container(root, output, source, config["image"])
    elif verified_receipt is not None:
        receipt["container_verification"] = reuse_verified(verified_receipt, output)
    if source_receipt(root) != source:
        raise ValueError("Source checkout changed during release preparation.")
    path = output / "release.json"
    path.write_text(encoded(receipt), encoding="utf-8")
    if receipt["container_verification"]["status"] == "passed":
        (output / "apply.ps1").write_text(
            APPLY.replace("<RECEIPT_HASH>", sha256(path)), encoding="utf-8"
        )
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    verification = parser.add_mutually_exclusive_group()
    verification.add_argument("--verify-container", action="store_true")
    verification.add_argument("--verified-receipt", type=Path)
    args = parser.parse_args()
    try:
        receipt = prepare(
            args.source_root,
            args.config,
            Path(__file__).with_name("containerapp.yaml"),
            args.output,
            args.verify_container,
            args.verified_receipt,
        )
    except (ValueError, KeyError, OSError, subprocess.SubprocessError, ET.ParseError) as error:
        print(f"Preparation failed: {error}", file=sys.stderr)
        return 1
    print(f"Prepared: {receipt}. No image was pushed and no deployment was applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
