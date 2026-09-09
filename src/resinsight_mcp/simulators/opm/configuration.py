"""Explicit configuration for the already approved local Flow runtime."""

import json
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from resinsight_mcp.contracts.errors import ContractError, Error, ErrorCode

FLOW_IMAGE = (
    "openporousmedia/opmreleases@"
    "sha256:810b1a2b72ee24a194df033781e82d57ad3a262167054953c0c3e37d9c0cbbc1"
)


class _Image(BaseModel):
    model_config = ConfigDict(extra="ignore")
    architecture: str = Field(alias="Architecture")
    operating_system: str = Field(alias="Os")
    repository_digests: tuple[str, ...] = Field(alias="RepoDigests")


class FlowConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    docker: Path = Path("/Applications/Docker.app/Contents/Resources/bin/docker")
    image: Literal[
        "openporousmedia/opmreleases@sha256:"
        "810b1a2b72ee24a194df033781e82d57ad3a262167054953c0c3e37d9c0cbbc1"
    ] = FLOW_IMAGE
    platform: Literal["linux/arm64"] = "linux/arm64"
    program_version: Literal["flow 2026.04"] = "flow 2026.04"

    @model_validator(mode="after")
    def check_executable(self) -> "FlowConfiguration":
        if not self.docker.is_absolute():
            raise ValueError("The Docker executable must use an absolute path.")
        return self

    def runtime_versions(self) -> tuple[str, str]:
        """Read the chosen client and daemon without pulling or launching an image."""
        try:
            completed = subprocess.run(
                (str(self.docker), "version", "--format", "{{json .}}"),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if completed.returncode != 0:
                raise ValueError(completed.stderr.strip())
            record = json.loads(completed.stdout)
            client = record["Client"]["Version"]
            server = record["Server"]["Version"]
            if (
                not isinstance(client, str)
                or not isinstance(server, str)
                or not client.strip()
                or not server.strip()
            ):
                raise ValueError("Docker version fields must contain nonempty text.")
            return client, server
        except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError) as error:
            raise ContractError(
                Error(code=ErrorCode.EXECUTION_FAILED, message=f"Docker is unavailable: {error}")
            ) from error

    def check_dependencies(self) -> None:
        """Reject unavailable or mismatched pinned runtimes without pulling or launching."""
        self.runtime_versions()
        try:
            completed = subprocess.run(
                (str(self.docker), "image", "inspect", self.image),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if completed.returncode != 0:
                raise ValueError(f"Pinned image inspection failed: {completed.stderr.strip()}")
            images = TypeAdapter(tuple[_Image, ...]).validate_json(completed.stdout)
            if len(images) != 1:
                raise ValueError("Pinned image inspection must return exactly one image.")
            image = images[0]
            if f"{image.operating_system}/{image.architecture}" != self.platform:
                raise ValueError("The local Flow image platform differs from the pinned platform.")
            if self.image not in image.repository_digests:
                raise ValueError("The local Flow image has no matching pinned repository digest.")
        except (OSError, subprocess.TimeoutExpired, ValueError) as error:
            raise ContractError(
                Error(
                    code=ErrorCode.EXECUTION_FAILED,
                    message=f"Flow runtime configuration is unavailable or mismatched: {error}",
                )
            ) from error
