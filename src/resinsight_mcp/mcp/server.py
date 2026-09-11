"""SDK request handling stays separate from durable service state."""

import json
import logging
from typing import Any

import anyio
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.shared.exceptions import McpError
from pydantic import AnyUrl, ValidationError

from resinsight_mcp.contracts.errors import (
    ContractError,
    Error,
    ErrorCode,
    Failure,
    MutationEffect,
    OperationResult,
)

from .catalog import CATALOG_RESOURCE, Bindings, Operation, build_catalog
from .content import encode_result

logger = logging.getLogger(__name__)


def _failure(error: Error, bindings: Bindings) -> types.CallToolResult:
    return encode_result(OperationResult[object](outcome=Failure(error=error)), bindings.workspaces)


def _call(
    operation: Operation[Any, Any], arguments: dict[str, Any], bindings: Bindings
) -> types.CallToolResult:
    try:
        request = operation.request.model_validate_json(json.dumps(arguments, allow_nan=False))
    except (ValidationError, ValueError, TypeError):
        return _failure(
            Error(
                code=ErrorCode.INVALID_MODEL,
                message="Arguments do not match the tool request schema.",
            ),
            bindings,
        )
    try:
        return encode_result(operation.invoke(request, bindings.workspaces), bindings.workspaces)
    except ContractError as exc:
        return _failure(exc.error, bindings)
    except Exception:
        logger.exception("Operation %s failed.", operation.name)
        return _failure(
            Error(
                code=ErrorCode.EXECUTION_FAILED,
                message="The service failed. Inspect the application log before retrying.",
                effect=MutationEffect.NOT_APPLIED
                if operation.read_only
                else MutationEffect.UNKNOWN,
            ),
            bindings,
        )


def create_server(bindings: Bindings) -> Server:
    """Create a protocol server without changing, selecting, or closing application sessions."""
    server = Server("resinsight-mcp")
    operations = {operation.name: operation for operation in build_catalog(bindings)}

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [operation.tool() for operation in operations.values()]

    @server.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        operation = operations.get(name)
        if operation is None:
            return _failure(
                Error(code=ErrorCode.UNSUPPORTED_OPERATION, message="This tool is not available."),
                bindings,
            )

        def invoke() -> types.CallToolResult:
            manager = bindings.workspace_manager
            if manager is None:
                return _call(operation, arguments, bindings)
            with manager.operation():
                return _call(operation, arguments, bindings)

        return await anyio.to_thread.run_sync(invoke)

    @server.list_resources()
    async def list_resources() -> list[types.Resource]:
        return [CATALOG_RESOURCE.model_copy(deep=True)]

    @server.read_resource()
    async def read_resource(uri: AnyUrl) -> list[ReadResourceContents]:
        if uri != CATALOG_RESOURCE.uri:
            raise McpError(
                types.ErrorData(
                    code=types.INVALID_PARAMS,
                    message="The resource is not available.",
                    data=Error(
                        code=ErrorCode.NOT_FOUND, message="The resource is not available."
                    ).model_dump(mode="json"),
                )
            )
        content = {
            "tools": [
                operation.tool().model_dump(mode="json", exclude_none=True)
                for operation in operations.values()
            ]
        }
        return [ReadResourceContents(content=json.dumps(content), mime_type="application/json")]

    return server
