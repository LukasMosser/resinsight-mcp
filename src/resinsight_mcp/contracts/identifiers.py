"""Opaque identifiers keep unrelated record kinds separate."""

import re
from typing import ClassVar, Self
from uuid import uuid4

from pydantic import ConfigDict, RootModel, field_validator


class Identifier(RootModel[str]):
    """An immutable, prefixed UUID value that serializes as a string."""

    model_config = ConfigDict(frozen=True, strict=True, revalidate_instances="always")
    prefix: ClassVar[str]

    @field_validator("root")
    @classmethod
    def check_kind(cls, value: str) -> str:
        if re.fullmatch(rf"{cls.prefix}_[0-9a-f]{{32}}", value) is None:
            raise ValueError(f"Use a {cls.prefix} identifier with 32 lowercase UUID digits.")
        return value

    @classmethod
    def new(cls) -> Self:
        """Create a fresh identifier of this record kind."""
        return cls(f"{cls.prefix}_{uuid4().hex}")

    def __str__(self) -> str:
        return self.root


class SessionId(Identifier):
    prefix = "session"


class RevisionId(Identifier):
    prefix = "revision"


class JobId(Identifier):
    prefix = "job"


class ResultId(Identifier):
    prefix = "result"


class ObservationId(Identifier):
    prefix = "observation"


class ConnectionId(Identifier):
    prefix = "connection"


class GridId(Identifier):
    prefix = "grid"


class ArtifactId(Identifier):
    prefix = "artifact"


class EditId(Identifier):
    prefix = "edit"
