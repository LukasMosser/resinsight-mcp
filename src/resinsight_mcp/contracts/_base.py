"""Common validation for immutable public records."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

type Text = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]


class Record(BaseModel):
    """Reject unknown fields, coercion, mutation, and nonfinite numbers."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_default=True,
        revalidate_instances="always",
        allow_inf_nan=False,
    )
