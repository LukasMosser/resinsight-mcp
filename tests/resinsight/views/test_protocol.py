"""The real MCP SDK carries view receipts and decoded native image content."""

import base64
import json
from io import BytesIO
from pathlib import Path

import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from PIL import Image

from resinsight_mcp.contracts.errors import Error, ErrorCode, Failure, OperationResult, Success
from resinsight_mcp.contracts.identifiers import EditId, ObservationId, SessionId
from resinsight_mcp.contracts.interfaces import ViewService
from resinsight_mcp.contracts.observations import (
    EditedView,
    Observation,
    RenderRequest,
    ViewContext,
    ViewEditReceipt,
    ViewUpdateRequest,
)
from resinsight_mcp.mcp import Bindings, create_server
from resinsight_mcp.resinsight.views._capture import capture
from resinsight_mcp.workspaces import SqliteWorkspaceStore


class RecordingViews:
    """Supply controlled views while retaining real image storage and transport."""

    def __init__(self, store: SqliteWorkspaceStore) -> None:
        self.store = store
        self.calls: list[object] = []
        self.current: Observation | None = None
        self.fail_export = False

    def apply(self, request: ViewUpdateRequest) -> OperationResult[EditedView]:
        self.calls.append(request)
        context = request.context.model_copy(
            update={"scene_version": request.context.scene_version + 1}
        )
        receipt = ViewEditReceipt(
            edit_id=EditId.new(),
            previous_scene_version=request.context.scene_version,
            context=context,
        )
        if self.fail_export:
            self.current = None
            observation = OperationResult[Observation](
                outcome=Failure(
                    error=Error(
                        code=ErrorCode.RENDER_FAILED, message="The controlled export failed."
                    )
                )
            )
        else:
            observation = self.render(
                RenderRequest(
                    result=self._result(context),
                    context=context,
                    width=request.width,
                    height=request.height,
                )
            )
        return OperationResult(
            outcome=Success(value=EditedView(edit=receipt, observation=observation))
        )

    def _result(self, context: ViewContext):
        result = self.store.get_result(context.model.session_id, context.result_id)
        assert isinstance(result.outcome, Success)
        return result.outcome.value

    def render(self, request: RenderRequest) -> OperationResult[Observation]:
        def export(folder: Path, width: int, height: int) -> None:
            Image.new("RGB", (width, height), "navy").save(folder / "frame.png")

        self.current = capture(self.store, request.context, request.width, request.height, export)
        return OperationResult(outcome=Success(value=self.current))

    def get_observation(
        self, session_id: SessionId, observation_id: ObservationId
    ) -> OperationResult[Observation]:
        self.calls.append((session_id, observation_id))
        if self.current is not None and self.current.observation_id == observation_id:
            return OperationResult(outcome=Success(value=self.current))
        return OperationResult(
            outcome=Failure(
                error=Error(
                    code=ErrorCode.STALE_OBJECT, message="The controlled scene has changed."
                )
            )
        )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_sdk_receives_view_receipt_and_fresh_image(
    store: SqliteWorkspaceStore, view_context: ViewContext
) -> None:
    views = RecordingViews(store)
    _contract: ViewService = views
    server = create_server(Bindings(workspaces=store, views=views))
    request = ViewUpdateRequest(context=view_context, width=80, height=60)
    async with create_connected_server_and_client_session(server) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        assert "view_apply" in tools and "view_render" in tools
        response = await client.call_tool("view_apply", request.model_dump(mode="json"))
        assert not response.isError
        result = OperationResult[EditedView].model_validate_json(
            json.dumps(response.structuredContent)
        )
        assert isinstance(result.outcome, Success)
        edited = result.outcome.value
        assert isinstance(edited.edit, ViewEditReceipt)
        assert edited.edit.previous_scene_version == view_context.scene_version
        assert isinstance(edited.observation.outcome, Success)
        observation = edited.observation.outcome.value
        assert observation.context == edited.edit.context
        assert [item.type for item in response.content] == ["text", "image"]
        content = response.content[1]
        assert content.type == "image"
        with Image.open(BytesIO(base64.b64decode(content.data))) as image:
            image.load()
            assert image.format == "PNG" and image.size == (80, 60)
        views.fail_export = True
        failed = await client.call_tool(
            "view_apply",
            request.model_copy(update={"context": observation.context}).model_dump(mode="json"),
        )
        assert not failed.isError
        assert [item.type for item in failed.content] == ["text"]
        failed_result = OperationResult[EditedView].model_validate_json(
            json.dumps(failed.structuredContent)
        )
        assert isinstance(failed_result.outcome, Success)
        assert failed_result.outcome.value.edit.effect == "applied"
        assert isinstance(failed_result.outcome.value.observation.outcome, Failure)
        old = await client.call_tool(
            "observation_get",
            {
                "session_id": str(view_context.model.session_id),
                "observation_id": str(observation.observation_id),
            },
        )
        assert old.isError
        assert views.calls[-1] == (view_context.model.session_id, observation.observation_id)
        assert isinstance(
            store.get_observation(
                view_context.model.session_id, observation.observation_id
            ).outcome,
            Success,
        )


@pytest.mark.anyio
async def test_view_binding_is_optional_and_rejects_unknown_session(
    store: SqliteWorkspaceStore, view_context: ViewContext
) -> None:
    async with create_connected_server_and_client_session(
        create_server(Bindings(workspaces=store))
    ) as client:
        assert "view_apply" not in {tool.name for tool in (await client.list_tools()).tools}
    views = RecordingViews(store)
    unknown = SessionId.new()
    data = view_context.model_dump(mode="json")
    data["model"]["session_id"] = str(unknown)
    data["case"]["context"]["session_id"] = str(unknown)
    data["view"]["context"]["session_id"] = str(unknown)
    request = ViewUpdateRequest.model_validate_json(
        json.dumps({"context": data, "width": 80, "height": 60})
    )
    async with create_connected_server_and_client_session(
        create_server(Bindings(workspaces=store, views=views))
    ) as client:
        response = await client.call_tool("view_apply", request.model_dump(mode="json"))
        assert response.isError
        result = OperationResult[EditedView].model_validate_json(
            json.dumps(response.structuredContent)
        )
        assert isinstance(result.outcome, Failure)
        assert result.outcome.error.code == ErrorCode.NOT_FOUND
        assert views.calls == []
