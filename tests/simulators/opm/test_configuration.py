"""Verify read-only pinned runtime checks through the Docker command boundary."""

import json
import subprocess
from typing import Any

import pytest

from resinsight_mcp.contracts.errors import ContractError, ErrorCode
from resinsight_mcp.simulators.opm import FlowConfiguration


@pytest.fixture
def image() -> dict[str, Any]:
    return {
        "Architecture": "arm64",
        "Os": "linux",
        "RepoDigests": [FlowConfiguration().image],
    }


def test_dependencies_check_versions_and_pinned_image_without_launch(
    image: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = []

    def command(argv: tuple[str, ...], **options: Any):
        commands.append(argv[1:])
        assert options["timeout"] == 10
        if argv[1] == "version":
            output = {"Client": {"Version": "29.3.1"}, "Server": {"Version": "29.3.1"}}
        else:
            output = [image]
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(output), stderr="")

    monkeypatch.setattr(subprocess, "run", command)
    configuration = FlowConfiguration()
    configuration.check_dependencies()
    assert commands == [
        ("version", "--format", "{{json .}}"),
        ("image", "inspect", configuration.image),
    ]


@pytest.mark.parametrize(
    "change,message",
    [
        ({"Architecture": "amd64"}, "platform differs"),
        (
            {"RepoDigests": ["another-image@sha256:" + "1" * 64]},
            "matching pinned repository digest",
        ),
    ],
)
def test_dependencies_reject_mismatched_local_image(
    image: dict[str, Any],
    change: dict[str, Any],
    message: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image.update(change)
    monkeypatch.setattr(FlowConfiguration, "runtime_versions", lambda self: ("29.3.1", "29.3.1"))
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, 0, stdout=json.dumps([image]), stderr=""
        ),
    )
    with pytest.raises(ContractError, match=message) as failure:
        FlowConfiguration().check_dependencies()
    assert failure.value.error.code == ErrorCode.EXECUTION_FAILED


def test_dependencies_reject_unavailable_image(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(FlowConfiguration, "runtime_versions", lambda self: ("29.3.1", "29.3.1"))
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, 1, stdout="", stderr="No such image: pinned digest"
        ),
    )
    with pytest.raises(ContractError, match="Pinned image inspection failed"):
        FlowConfiguration().check_dependencies()


def test_dependencies_stop_after_daemon_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    commands = []

    def command(argv: tuple[str, ...], **options: Any):
        commands.append(argv[1])
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="Daemon is unavailable")

    monkeypatch.setattr(subprocess, "run", command)
    with pytest.raises(ContractError, match="Docker is unavailable"):
        FlowConfiguration().check_dependencies()
    assert commands == ["version"]
