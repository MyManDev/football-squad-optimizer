from __future__ import annotations

import copy
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
SPEC = importlib.util.spec_from_file_location(
    "backend_release_candidate", DEPLOY / "prepare_backend_release.py"
)
assert SPEC is not None and SPEC.loader is not None
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


@pytest.fixture
def config() -> dict[str, object]:
    return json.loads((DEPLOY / "backend-release.example.json").read_text())


@pytest.mark.parametrize(
    "field,value",
    [
        ("image", "example.azurecr.io/squadopt-backend:latest"),
        ("image", "example.azurecr.io/squadopt-backend@sha256:" + "A" * 64),
        ("image", "example.azurecr.io/a/../b@sha256:" + "a" * 64),
        ("environment_id", "https://example.invalid/environment"),
        ("registry_identity_id", "system"),
        ("allowed_origins", ["*"]),
        ("allowed_origins", ["https://example.pages.dev/path"]),
        ("allowed_origins", ["https://user:pass@example.pages.dev"]),
        ("allowed_origins", ["https://example.pages.dev?token=x"]),
        ("allowed_origins", ["https://example.pages.dev:99999"]),
        ("allowed_origins", ["https://.."]),
        ("allowed_origins", []),
        ("allowed_origins", ["https://example.pages.dev", "https://example.pages.dev"]),
        ("operation", "delete"),
        ("app_name", "backend; Write-Output surprise"),
    ],
)
def test_invalid_operator_values_are_refused(
    config: dict[str, object], field: str, value: object
) -> None:
    config[field] = value
    with pytest.raises(ValueError):
        release.validate_config(config)


def test_unknown_fields_are_rejected_without_echoing_value(config: dict[str, object]) -> None:
    config["credential"] = "must-not-be-logged"
    with pytest.raises(ValueError) as error:
        release.validate_config(config)
    assert "must-not-be-logged" not in str(error.value)


def test_rendered_pair_keeps_runtime_and_storage_contract(
    config: dict[str, object], tmp_path: Path
) -> None:
    root = tmp_path / "source"
    root.mkdir()
    config_path = tmp_path / "operator.json"
    config_path.write_text(json.dumps(config))
    source = {"commit": "b" * 40, "tree": "c" * 40, "build_inputs": {}}
    output = root / ".pt" / "release"
    with (
        patch.object(release, "source_receipt", return_value=source),
        patch.object(release, "command") as command,
    ):
        receipt = release.prepare(root, config_path, DEPLOY / "containerapp.yaml", output, False)
    command.assert_not_called()
    manifest = json.loads((output / "containerapp.yaml").read_text())
    properties = manifest["properties"]
    api, worker = properties["template"]["containers"]
    assert api["image"] == worker["image"] == config["image"]
    assert api["command"] == ["uvicorn"]
    assert worker["args"] == ["-m", "squadopt.platform.advice_worker"]
    assert api["env"] == worker["env"]
    assert "SQUADOPT_REPOSITORY_COMMIT" not in {item["name"] for item in api["env"]}
    assert api["volumeMounts"] == worker["volumeMounts"]
    assert properties["template"]["scale"] == {"minReplicas": 1, "maxReplicas": 1}
    assert properties["configuration"]["ingress"]["external"] is False
    assert "targetContainerName" not in properties["configuration"]["ingress"]
    assert {p["type"] for p in api["probes"]} == {"Liveness", "Startup"}
    assert manifest["identity"]["userAssignedIdentities"] == {config["registry_identity_id"]: {}}
    assert (
        properties["configuration"]["registries"][0]["identity"] == config["registry_identity_id"]
    )
    record = json.loads(receipt.read_text())
    assert record["source"]["commit"] == source["commit"]
    assert record["container_verification"] == {"status": "not_requested"}
    assert record["cloud_mount_acceptance"] == "not_run"
    assert record["yaml_sha256"] == release.sha256(output / "containerapp.yaml")
    assert not (output / "apply.ps1").exists()


@pytest.mark.parametrize("destination", ["outside", ".pt"])
def test_output_must_be_a_child_of_scratch(tmp_path: Path, destination: str) -> None:
    with pytest.raises(ValueError, match="Output must"):
        release.prepare(
            tmp_path,
            DEPLOY / "backend-release.example.json",
            DEPLOY / "containerapp.yaml",
            tmp_path / destination,
            False,
        )


def test_existing_release_is_never_overwritten(tmp_path: Path) -> None:
    output = tmp_path / ".pt" / "existing"
    output.mkdir(parents=True)
    sentinel = output / "keep"
    sentinel.write_text("original")
    with pytest.raises(ValueError, match="already exists"):
        release.prepare(
            tmp_path,
            DEPLOY / "backend-release.example.json",
            DEPLOY / "containerapp.yaml",
            output,
            False,
        )
    assert sentinel.read_text() == "original"


def test_dirty_checkout_cannot_get_a_source_receipt(tmp_path: Path) -> None:
    with (
        patch.object(release, "command", side_effect=[str(tmp_path.resolve()), " M src/code.py"]),
        pytest.raises(ValueError, match="clean"),
    ):
        release.source_receipt(tmp_path.resolve())


def test_template_refuses_unresolved_or_partial_placeholders() -> None:
    with pytest.raises(ValueError, match="placeholder"):
        release.render({"image": "registry/<IMAGE>"}, {"<IMAGE>": "value"})


def test_source_change_does_not_publish_an_apply_script(tmp_path: Path) -> None:
    output = tmp_path / ".pt" / "release"
    with (
        patch.object(release, "source_receipt", side_effect=[{"commit": "a"}, {"commit": "b"}]),
        pytest.raises(ValueError, match="changed"),
    ):
        release.prepare(
            tmp_path,
            DEPLOY / "backend-release.example.json",
            DEPLOY / "containerapp.yaml",
            output,
            False,
        )
    assert not (output / "release.json").exists()
    assert not (output / "apply.ps1").exists()


def test_skipped_container_gate_cannot_be_reported_as_verified(tmp_path: Path) -> None:
    image_id = "sha256:" + "a" * 64
    source = {"commit": "b" * 40}
    image = {
        "Id": image_id,
        "Architecture": "amd64",
        "Os": "linux",
        "Config": {
            "Env": ["SQUADOPT_REPOSITORY_COMMIT=" + source["commit"]],
            "Labels": {"org.opencontainers.image.revision": source["commit"]},
        },
    }

    def fake_logged(arguments: list[str], root: Path, output: Path, env: dict[str, str]) -> None:
        if arguments[0] == "docker":
            assert f"SQUADOPT_REPOSITORY_COMMIT={source['commit']}" in arguments
            (tmp_path / "image.id").write_text(image_id)
        else:
            assert env["SQUADOPT_CONTAINER_IMAGE"] == image_id
            assert env["PYTHONPATH"].startswith(str(root / "src"))
            (tmp_path / "container-smoke.xml").write_text(
                '<testsuite><testcase name="ignored"><skipped /></testcase></testsuite>'
            )

    with (
        patch.object(release, "logged", side_effect=fake_logged),
        patch.object(release, "command", return_value=json.dumps([image])),
        pytest.raises(ValueError, match="skipped suite"),
    ):
        release.verify_container(tmp_path, tmp_path, source, "unused")


@pytest.mark.parametrize("mutation", ["label", "environment", "architecture"])
def test_image_identity_cannot_claim_another_checkout(mutation: str) -> None:
    image = {
        "Id": "sha256:" + "a" * 64,
        "Architecture": "amd64",
        "Os": "linux",
        "Config": {
            "Env": ["SQUADOPT_REPOSITORY_COMMIT=" + "b" * 40],
            "Labels": {"org.opencontainers.image.revision": "b" * 40},
        },
    }
    assert release.validate_image_inspection(image, "b" * 40) == image["Id"]
    broken = copy.deepcopy(image)
    if mutation == "label":
        broken["Config"]["Labels"]["org.opencontainers.image.revision"] = "c" * 40
    elif mutation == "environment":
        broken["Config"]["Env"] = ["SQUADOPT_REPOSITORY_COMMIT=" + "c" * 40]
    else:
        broken["Architecture"] = "arm64"
    with pytest.raises(ValueError):
        release.validate_image_inspection(broken, "b" * 40)


def write_junit(path: Path, nodeids: list[str]) -> None:
    path.write_text(
        '<testsuite errors="0" failures="0" skipped="0">'
        + "".join(
            '<testcase classname="tests.integration.test_backend_container" name="'
            + nodeid.split("::")[1]
            + '" />'
            for nodeid in nodeids
        )
        + "</testsuite>"
    )


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "extra", "wrong_class"])
def test_only_the_complete_mandatory_suite_is_evidence(tmp_path: Path, mutation: str) -> None:
    nodeids = list(release.CONTAINER_TESTS)
    if mutation == "missing":
        nodeids.pop()
    elif mutation == "duplicate":
        nodeids.append(nodeids[0])
    elif mutation == "extra":
        nodeids.append("tests/integration/test_backend_container.py::test_unrelated")
    path = tmp_path / "junit.xml"
    write_junit(path, nodeids)
    if mutation == "wrong_class":
        path.write_text(path.read_text().replace("tests.integration", "elsewhere.integration"))
    with pytest.raises(ValueError, match="exactly once"):
        release.validate_container_junit(path)


def valid_image(commit: str) -> dict[str, object]:
    return {
        "Id": "sha256:" + "a" * 64,
        "Os": "linux",
        "Architecture": "amd64",
        "Config": {
            "Env": ["SQUADOPT_REPOSITORY_COMMIT=" + commit],
            "Labels": {"org.opencontainers.image.revision": commit},
        },
    }


def test_inherited_pytest_selection_cannot_weaken_verification(tmp_path: Path) -> None:
    source = {"commit": "b" * 40}
    image = valid_image(source["commit"])

    def fake_logged(arguments: list[str], root: Path, output: Path, env: dict[str, str]) -> None:
        assert "PYTEST_ADDOPTS" not in env
        assert "PYTEST_PLUGINS" not in env
        assert env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
        assert env["TMP"] == env["TEMP"] == env["TMPDIR"] == str(tmp_path / "tmp")
        if arguments[0] == "docker":
            (tmp_path / "image.id").write_text(str(image["Id"]))
        else:
            assert "addopts=" in arguments
            write_junit(tmp_path / "container-smoke.xml", release.CONTAINER_TESTS)

    with (
        patch.dict(os.environ, {"PYTEST_ADDOPTS": "-k absent", "PYTEST_PLUGINS": "custom"}),
        patch.object(release, "logged", side_effect=fake_logged),
        patch.object(release, "command", return_value=json.dumps([image])),
        patch.object(release, "source_receipt", return_value=source),
    ):
        proof = release.verify_container(tmp_path, tmp_path, source, "unused")
    assert proof["test_nodeids"] == release.CONTAINER_TESTS
    assert proof["temporary_environment"]["TEMP"] == str(tmp_path / "tmp")


def retained_evidence(root: Path) -> Path:
    root.mkdir()
    source = {"commit": "b" * 40}
    image = valid_image(source["commit"])
    junit = root / "container-smoke.xml"
    inspection = root / "image-inspection.json"
    write_junit(junit, release.CONTAINER_TESTS)
    inspection.write_text(json.dumps(image))
    proof = release.verification_record(source, image, junit, inspection)
    path = root / "release.json"
    path.write_text(
        json.dumps(
            {
                "schema": "backend_release_preparation_v1",
                "source": {"commit": "c" * 40},
                "container_verification": proof,
            }
        )
    )
    return path


def test_rollback_uses_prior_tested_commit_with_a_different_preparer_head(tmp_path: Path) -> None:
    previous = retained_evidence(tmp_path / "previous")
    output = tmp_path / ".pt" / "rollback"
    with (
        patch.object(release, "source_receipt", return_value={"commit": "d" * 40}),
        patch.object(release, "verify_container") as rebuild,
        patch.object(release, "command") as command,
    ):
        path = release.prepare(
            tmp_path,
            DEPLOY / "backend-release.example.json",
            DEPLOY / "containerapp.yaml",
            output,
            False,
            previous,
        )
    rebuild.assert_not_called()
    command.assert_not_called()
    record = json.loads(path.read_text())
    assert record["source"]["commit"] == "d" * 40
    assert record["container_verification"]["tested_commit"] == "b" * 40
    assert (output / "apply.ps1").exists()


def test_changed_retained_evidence_is_rejected(tmp_path: Path) -> None:
    previous = retained_evidence(tmp_path / "previous")
    (previous.parent / "container-smoke.xml").write_text("changed")
    with pytest.raises(ValueError, match="evidence changed"):
        release.reuse_verified(previous, tmp_path)


POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required to exercise owner preflight")
@pytest.mark.parametrize(
    "mutation", ["none", "id", "digest", "label", "environment", "architecture", "missing"]
)
def test_owner_preflight_binds_digest_to_tested_image_before_azure(
    tmp_path: Path, mutation: str, config: dict[str, object]
) -> None:
    previous = retained_evidence(tmp_path / "previous")
    output = tmp_path / ".pt" / "release"
    with patch.object(release, "source_receipt", return_value={"commit": "d" * 40}):
        release.prepare(
            tmp_path,
            DEPLOY / "backend-release.example.json",
            DEPLOY / "containerapp.yaml",
            output,
            False,
            previous,
        )
    image = valid_image("b" * 40)
    image["RepoDigests"] = [config["image"]]
    if mutation == "id":
        image["Id"] = "sha256:" + "f" * 64
    elif mutation == "digest":
        image["RepoDigests"] = ["example.azurecr.io/unrelated@sha256:" + "f" * 64]
    elif mutation == "label":
        image["Config"]["Labels"]["org.opencontainers.image.revision"] = "d" * 40
    elif mutation == "environment":
        image["Config"]["Env"] = ["SQUADOPT_REPOSITORY_COMMIT=" + "d" * 40]
    elif mutation == "architecture":
        image["Architecture"] = "arm64"
    (output / "mock-image.json").write_text(json.dumps([image]))
    harness = output / "test-preflight.ps1"
    harness.write_text(
        "$ErrorActionPreference = 'Stop'\n"
        "function docker {\n"
        " if ($args[0] -ne 'image' -or $args[1] -ne 'inspect') {\n"
        " throw 'Unexpected Docker mutation' }\n"
        + (
            " $global:LASTEXITCODE = 1; return\n"
            if mutation == "missing"
            else " $global:LASTEXITCODE = 0\n"
            " Get-Content -LiteralPath (Join-Path $PSScriptRoot 'mock-image.json') -Raw\n"
        )
        + "}\nfunction az { throw 'Azure must never be invoked in this test' }\n"
        "& (Join-Path $PSScriptRoot 'apply.ps1') -PreflightOnly\n"
    )
    result = subprocess.run(
        [str(POWERSHELL), "-NoProfile", "-File", str(harness)],
        capture_output=True,
        text=True,
        check=False,
    )
    if mutation == "none":
        assert result.returncode == 0, result.stderr
        assert "Local image association verified" in result.stdout
    else:
        assert result.returncode != 0
    assert "Azure must never" not in result.stderr
