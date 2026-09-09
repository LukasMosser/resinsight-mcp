"""Encode operation records and validated images for MCP clients."""

import base64
from io import BytesIO

from mcp.types import CallToolResult, ImageContent, TextContent
from PIL import Image

from resinsight_mcp.contracts.errors import (
    ContractError,
    Error,
    ErrorCode,
    Failure,
    OperationResult,
    Success,
)
from resinsight_mcp.contracts.interfaces import WorkspaceStore
from resinsight_mcp.contracts.observations import EditedView, ImageArtifact, Observation
from resinsight_mcp.results.records import EditedSummaryPlot, SummaryObservation


def _image(artifact: ImageArtifact, store: WorkspaceStore) -> ImageContent | Failure:
    try:
        with store.open_artifact(artifact.artifact) as stream:
            data = stream.read()
        with Image.open(BytesIO(data)) as image:
            if image.format != "PNG" or image.size != (artifact.width, artifact.height):
                return Failure(
                    error=Error(
                        code=ErrorCode.RENDER_FAILED,
                        message="The observation image does not match its declared PNG dimensions.",
                    )
                )
            image.load()
        return ImageContent(
            type="image", data=base64.b64encode(data).decode("ascii"), mimeType="image/png"
        )
    except ContractError as exc:
        return Failure(error=exc.error)
    except Exception:
        return Failure(
            error=Error(
                code=ErrorCode.RENDER_FAILED,
                message="The observation image could not be read and decoded.",
            )
        )


def encode_result[T](result: OperationResult[T], store: WorkspaceStore) -> CallToolResult:
    """Preserve applied edits when their image cannot be delivered."""
    encoded: OperationResult[T] | OperationResult[object] = result
    native_image: ImageContent | None = None
    if isinstance(result.outcome, Success):
        value = result.outcome.value
        observation = None
        if isinstance(value, (Observation, SummaryObservation)):
            observation = value
        elif isinstance(value, (EditedView, EditedSummaryPlot)) and isinstance(
            value.observation.outcome, Success
        ):
            observation = value.observation.outcome.value
        if observation is not None:
            image_result = _image(observation.image, store)
            if isinstance(image_result, ImageContent):
                native_image = image_result
            elif isinstance(value, EditedView):
                edited = EditedView(
                    edit=value.edit,
                    observation=OperationResult[Observation](outcome=image_result),
                )
                encoded = OperationResult[object](outcome=Success(value=edited))
            elif isinstance(value, EditedSummaryPlot):
                summary = EditedSummaryPlot(
                    edit=value.edit,
                    observation=OperationResult[SummaryObservation](outcome=image_result),
                )
                encoded = OperationResult[object](outcome=Success(value=summary))
            else:
                encoded = OperationResult[object](outcome=image_result)
    response = CallToolResult(
        content=[TextContent(type="text", text=encoded.model_dump_json())],
        structuredContent=encoded.model_dump(mode="json"),
        isError=isinstance(encoded.outcome, Failure),
    )
    if native_image is not None:
        response.content.append(native_image)
    return response
