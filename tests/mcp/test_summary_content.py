"""Summary images retain verified values and confirmed edits at the MCP boundary."""

import base64
import json
from io import BytesIO

import pytest
from mcp.types import ImageContent, TextContent
from PIL import Image
from results.conftest import publish, store
from results.test_loading import setup
from results.test_queries import curve

from resinsight_mcp.contracts.errors import (
    ContractError,
    Error,
    ErrorCode,
    Failure,
    OperationResult,
    Success,
)
from resinsight_mcp.mcp.content import encode_result
from resinsight_mcp.results import EditedSummaryPlot, SummaryPlotRequest

__all__ = ["publish", "store"]


@pytest.mark.parametrize("delivery", ["valid", "missing", "dimensions", "native-failed"])
def test_summary_delivery_preserves_edit_and_exact_curve(
    store, publish, tmp_path, monkeypatch, delivery
):
    result, _, dataset = publish()
    results, _, _, _, backend, context = setup(store, result, tmp_path)
    if delivery == "native-failed":
        backend.export = False
    operation = results.show_curve(
        SummaryPlotRequest(context=context, query=curve(result), width=80, height=60)
    )
    assert isinstance(operation.outcome, Success)
    original = operation.outcome.value
    if delivery in {"missing", "dimensions"}:
        assert isinstance(original.observation.outcome, Success)
        image = original.observation.outcome.value.image
        open_artifact = store.open_artifact

        def changed_image(reference):
            if reference != image.artifact:
                return open_artifact(reference)
            if delivery == "missing":
                raise ContractError(
                    Error(code=ErrorCode.NOT_FOUND, message="The summary image is missing.")
                )
            stream = BytesIO()
            Image.new("RGB", (20, 10), "white").save(stream, format="PNG")
            stream.seek(0)
            return stream

        monkeypatch.setattr(store, "open_artifact", changed_image)
    response = encode_result(operation, store)
    assert response.isError is False
    text = response.content[0]
    assert isinstance(text, TextContent)
    assert json.loads(text.text) == response.structuredContent
    restored = OperationResult[EditedSummaryPlot].model_validate_json(text.text).outcome
    assert isinstance(restored, Success)
    assert restored.value.edit == original.edit
    assert restored.value.edit.effect == "applied"
    assert restored.value.edit.curve.result == result
    assert restored.value.edit.curve.values == dataset.curves[0].values
    observation = restored.value.observation.outcome
    if delivery == "valid":
        assert isinstance(observation, Success)
        assert observation.value.curve == original.edit.curve
        assert len(response.content) == 2
        image_content = response.content[1]
        assert isinstance(image_content, ImageContent)
        assert image_content.mimeType == "image/png"
        with Image.open(BytesIO(base64.b64decode(image_content.data))) as decoded:
            decoded.load()
            assert decoded.size == (80, 60)
            assert decoded.format == "PNG"
    else:
        assert isinstance(observation, Failure)
        assert len(response.content) == 1
        if delivery == "native-failed":
            assert response.structuredContent == operation.model_dump(mode="json")
