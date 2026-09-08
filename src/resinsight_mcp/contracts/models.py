"""Immutable input references and preparation records."""

from enum import StrEnum
from typing import Annotated, Self

from pydantic import Field, model_validator

from ._base import Record, Text
from .engineering import CoordinateFrame, ModelRef, UnitSystem
from .identifiers import ArtifactId, SessionId


class Session(Record):
    """A durable workspace identity, independent of any client connection."""

    session_id: SessionId
    name: Text


class ArtifactRef(Record):
    session_id: SessionId
    artifact_id: ArtifactId


class ModelInputs(Record):
    artifacts: Annotated[tuple[ArtifactId, ...], Field(min_length=1)]
    entrypoint: ArtifactId

    @model_validator(mode="after")
    def check_entrypoint(self) -> Self:
        if len(set(self.artifacts)) != len(self.artifacts):
            raise ValueError("Input artifact identifiers must be unique.")
        if self.entrypoint not in self.artifacts:
            raise ValueError("The entrypoint must identify one of the model inputs.")
        return self


class ModelRevision(Record):
    model: ModelRef
    inputs: ModelInputs
    unit_system: UnitSystem
    coordinates: CoordinateFrame
    parent: ModelRef | None = None

    @model_validator(mode="after")
    def check_parent(self) -> Self:
        if self.parent is not None:
            if self.parent.session_id != self.model.session_id:
                raise ValueError("A revision parent must belong to the same session.")
            if self.parent == self.model:
                raise ValueError("A revision cannot be its own parent.")
        return self


class Backend(StrEnum):
    OPM_FLOW = "opm_flow"
    JULIA = "julia"


class PreparationRequest(Record):
    revision: ModelRevision
    backend: Backend


class PreparedModel(Record):
    """Preparation verifies this fixed revision without editing its inputs."""

    revision: ModelRevision
    backend: Backend
