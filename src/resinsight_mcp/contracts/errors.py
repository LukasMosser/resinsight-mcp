"""Stable errors and explicit operation outcomes."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from ._base import Record, Text


class ErrorCode(StrEnum):
    BUSY = "busy"
    LOST_CONNECTION = "lost_connection"
    STALE_OBJECT = "stale_object"
    INVALID_MODEL = "invalid_model"
    UNSUPPORTED_OPERATION = "unsupported_operation"
    INVALID_TRANSITION = "invalid_transition"
    RENDER_FAILED = "render_failed"
    NOT_FOUND = "not_found"
    EXECUTION_FAILED = "execution_failed"


class MutationEffect(StrEnum):
    NOT_APPLIED = "not_applied"
    UNKNOWN = "unknown"


class Error(Record):
    code: ErrorCode
    message: Text
    effect: MutationEffect = MutationEffect.NOT_APPLIED


class ContractError(Exception):
    """A policy failure with a serializable error record."""

    def __init__(self, error: Error) -> None:
        self.error = error
        super().__init__(error.message)


class Success[T](Record):
    status: Literal["success"] = "success"
    value: T


class Failure(Record):
    status: Literal["failure"] = "failure"
    error: Error


class OperationResult[T](Record):
    outcome: Annotated[Success[T] | Failure, Field(discriminator="status")]
