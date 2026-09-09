"""Translate known result failures without hiding unexpected errors."""

from collections.abc import Callable
from functools import wraps
from typing import NoReturn

from pydantic import ValidationError

from resinsight_mcp.contracts.errors import (
    ContractError,
    Error,
    ErrorCode,
    Failure,
    OperationResult,
    Success,
)


def fail(code: ErrorCode, message: str) -> NoReturn:
    raise ContractError(Error(code=code, message=message))


def value[T](result: OperationResult[T]) -> T:
    if isinstance(result.outcome, Failure):
        raise ContractError(result.outcome.error)
    return result.outcome.value


def operation[**P, T](method: Callable[P, T]) -> Callable[P, OperationResult[T]]:
    @wraps(method)
    def run(*args: P.args, **kwargs: P.kwargs) -> OperationResult[T]:
        try:
            return OperationResult(outcome=Success(value=method(*args, **kwargs)))
        except ContractError as error:
            return OperationResult(outcome=Failure(error=error.error))
        except (ValidationError, UnicodeError) as error:
            return OperationResult(
                outcome=Failure(
                    error=Error(
                        code=ErrorCode.INVALID_MODEL, message=f"Invalid result metadata: {error}"
                    )
                )
            )
        except OSError:
            return OperationResult(
                outcome=Failure(
                    error=Error(
                        code=ErrorCode.STORAGE_FAILED, message="The result file operation failed."
                    )
                )
            )

    return run
