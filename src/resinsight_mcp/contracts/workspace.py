"""Artifact metadata, saved-project checkpoints, and explicit recovery outcomes."""

import unicodedata
from enum import StrEnum
from typing import Self

from pydantic import field_validator, model_validator

from ._base import Record, Text
from .engineering import ModelRef
from .errors import Error
from .identifiers import ArtifactId, CheckpointId, ResultId, SessionId
from .jobs import Job
from .models import ArtifactRef


class ArtifactKind(StrEnum):
    INPUT = "input"
    OUTPUT = "output"
    IMAGE = "image"
    LOG = "log"
    PROJECT = "project"
    METADATA = "metadata"


class Artifact(Record):
    """An immutable file identity with a logical, relative name."""

    ref: ArtifactRef
    relative_path: Text
    kind: ArtifactKind

    @field_validator("relative_path")
    @classmethod
    def check_relative_path(cls, value: str) -> str:
        parts = value.split("/")
        if (
            any(part in {"", ".", ".."} for part in parts)
            or "\\" in value
            or ":" in value
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
        ):
            raise ValueError("Use a relative file path without dot segments or special separators.")
        return value

    @property
    def path_key(self) -> str:
        """Detect names that collide across the supported macOS and Linux filesystems."""
        return unicodedata.normalize("NFC", self.relative_path).casefold()


class ProjectCheckpoint(Record):
    """Bind a supplied saved-project artifact to its exact stored input revision."""

    checkpoint_id: CheckpointId
    name: Text
    model: ModelRef
    project: ArtifactRef
    result_ids: tuple[ResultId, ...] = ()

    @model_validator(mode="after")
    def check_session(self) -> Self:
        if len(set(self.result_ids)) != len(self.result_ids):
            raise ValueError("Checkpoint result identifiers must be unique.")
        if self.project.session_id != self.model.session_id:
            raise ValueError("The saved project and revision must belong to the same session.")
        return self


class ArtifactProblem(Record):
    artifact: ArtifactRef
    error: Error


class RecoveryReport(Record):
    session_id: SessionId
    jobs: tuple[Job, ...]
    removed_artifacts: tuple[ArtifactId, ...]
    unavailable_artifacts: tuple[ArtifactProblem, ...]

    @model_validator(mode="after")
    def check_session(self) -> Self:
        if any(job.model.session_id != self.session_id for job in self.jobs):
            raise ValueError("Recovered jobs must belong to the requested session.")
        if any(item.artifact.session_id != self.session_id for item in self.unavailable_artifacts):
            raise ValueError("Unavailable artifacts must belong to the requested session.")
        return self
