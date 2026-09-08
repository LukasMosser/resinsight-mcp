"""Public failures retain the distinction clients need before retrying."""

import json

import pytest
from pydantic import ValidationError

from resinsight_mcp.contracts.errors import (
    Error,
    ErrorCode,
    Failure,
    MutationEffect,
    OperationResult,
)


@pytest.mark.parametrize(
    "code",
    [
        ErrorCode.BUSY,
        ErrorCode.LOST_CONNECTION,
        ErrorCode.STALE_OBJECT,
        ErrorCode.INVALID_MODEL,
        ErrorCode.UNSUPPORTED_OPERATION,
    ],
)
def test_error_codes_survive_public_json(code: ErrorCode) -> None:
    response = OperationResult[str](
        outcome=Failure(error=Error(code=code, message="The requested operation did not complete."))
    )
    restored = OperationResult[str].model_validate_json(response.model_dump_json())
    assert isinstance(restored.outcome, Failure)
    assert restored.outcome.error.code == code
    assert restored.outcome.error.effect == MutationEffect.NOT_APPLIED


def test_lost_reply_can_preserve_unknown_mutation_effect() -> None:
    error = Error(
        code=ErrorCode.LOST_CONNECTION,
        message="Connection lost before edit acknowledgement.",
        effect=MutationEffect.UNKNOWN,
    )
    assert Error.model_validate_json(error.model_dump_json()).effect == MutationEffect.UNKNOWN


def test_failure_cannot_also_carry_a_success_value() -> None:
    payload = {
        "outcome": {
            "status": "failure",
            "error": {"code": "busy", "message": "Application busy"},
            "value": "old result",
        }
    }
    with pytest.raises(ValidationError) as invalid:
        OperationResult[str].model_validate_json(json.dumps(payload))
    assert any(error["type"] == "extra_forbidden" for error in invalid.value.errors())
