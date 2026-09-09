"""Verify daemon-owned container identity independently of the local client."""

import json
import subprocess
import time

from pydantic import BaseModel, ConfigDict, Field

from resinsight_mcp.contracts.jobs import JobSubmission

LABEL = "org.resinsight-mcp.owner"
COMMAND_TIMEOUT = 10.0


class ContainerOwnershipError(RuntimeError):
    """A Docker operation cannot establish the recorded container outcome."""


class _State(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    running: bool = Field(alias="Running")
    status: str = Field(alias="Status")
    exit_code: int = Field(alias="ExitCode")


class _Configuration(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    image: str = Field(alias="Image")
    labels: dict[str, str] = Field(alias="Labels")


class ContainerSnapshot(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    container_id: str = Field(alias="Id")
    name: str = Field(alias="Name")
    configuration: _Configuration = Field(alias="Config")
    state: _State = Field(alias="State")


class OwnedContainer:
    """Keep stopped containers until explicit verified removal."""

    def __init__(self, submission: JobSubmission, container_id: str | None = None) -> None:
        if submission.execution is None:
            raise ValueError("Container ownership requires Docker execution metadata.")
        self.submission = submission
        self.execution = submission.execution
        self.container_id = container_id

    def _command(self, *arguments: str, timeout: float = COMMAND_TIMEOUT) -> str:
        try:
            completed = subprocess.run(
                (self.submission.argv[0], *arguments),
                cwd=self.submission.working_directory,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ContainerOwnershipError(f"Docker operation is uncertain: {error}") from error
        if completed.returncode != 0:
            raise ContainerOwnershipError(
                f"Docker {arguments[0]} failed: {completed.stderr.strip()}"
            )
        return completed.stdout

    def create(self, timeout: float) -> str:
        execution = self.execution
        limits = self.submission.limits
        arguments = [
            "create",
            "--pull=never",
            "--network=none",
            "--platform",
            execution.platform,
            "--cpus",
            str(limits.cpu_count),
            "--memory",
            f"{limits.memory_mib}m",
            "--name",
            execution.container_name,
            "--label",
            f"{LABEL}={execution.ownership_token}",
            "--workdir",
            execution.working_directory,
        ]
        for mount in execution.mounts:
            specification = f"type=bind,source={mount.source},target={mount.target}"
            if mount.read_only:
                specification += ",readonly"
            arguments.extend(("--mount", specification))
        arguments.extend((execution.image_digest, *execution.command))
        print(f"Docker create arguments: {json.dumps(arguments)}", flush=True)
        self.container_id = self._command(*arguments, timeout=timeout).strip()
        snapshot = self.inspect()
        if snapshot.state.status != "created":
            raise ContainerOwnershipError("A newly created container has already changed state.")
        return snapshot.container_id

    def inspect(self) -> ContainerSnapshot:
        identity = self.container_id or self.execution.container_name
        try:
            records = json.loads(self._command("container", "inspect", identity))
            if not isinstance(records, list) or len(records) != 1:
                raise ValueError("Expected one container inspection.")
            snapshot = ContainerSnapshot.model_validate(records[0])
        except (ValueError, TypeError) as error:
            raise ContainerOwnershipError(f"Docker inspection is invalid: {error}") from error
        expected = self.execution
        if (
            (self.container_id is not None and snapshot.container_id != self.container_id)
            or snapshot.name != f"/{expected.container_name}"
            or snapshot.configuration.image != expected.image_digest
            or snapshot.configuration.labels.get(LABEL) != expected.ownership_token
        ):
            raise ContainerOwnershipError("The container identity differs from the saved owner.")
        return snapshot

    def find(self) -> ContainerSnapshot | None:
        """Establish absence only from a successful complete daemon inventory."""
        output = self._command("container", "ls", "--all", "--no-trunc", "--format", "{{json .}}")
        try:
            records = [json.loads(line) for line in output.splitlines() if line.strip()]
            identities = [(record["ID"], record["Names"]) for record in records]
            if any(not isinstance(value, str) for pair in identities for value in pair):
                raise ValueError("Container inventory identities must contain text.")
        except (ValueError, KeyError, TypeError) as error:
            raise ContainerOwnershipError(f"Docker inventory is invalid: {error}") from error
        if any(
            identity == self.container_id or name == self.execution.container_name
            for identity, name in identities
        ):
            return self.inspect()
        return None

    def start(self, deadline: float) -> tuple[str, ...]:
        snapshot = self.inspect()
        if snapshot.state.status != "created":
            raise ContainerOwnershipError("Only a recorded, newly created container can start.")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ContainerOwnershipError("The wall deadline expired before container start.")
        try:
            self._command("start", snapshot.container_id, timeout=min(COMMAND_TIMEOUT, remaining))
        except ContainerOwnershipError:
            self.stop()
            raise
        return (self.submission.argv[0], "logs", "--follow", snapshot.container_id)

    def stop(self) -> None:
        snapshot = self.inspect()
        if snapshot.state.running:
            self._command("stop", "--time", "1", snapshot.container_id)
        if self.inspect().state.running:
            raise ContainerOwnershipError("Docker did not confirm container termination.")

    def remove(self) -> None:
        snapshot = self.inspect()
        if snapshot.state.running:
            raise ContainerOwnershipError("A running container cannot be removed as completed.")
        self._command("rm", snapshot.container_id)
