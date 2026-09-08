"""A fresh image proves a particular scene; failed renders never erase edits."""

import base64
import json
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pytest
from mcp.types import ImageContent, TextContent
from PIL import Image

from resinsight_mcp.contracts.engineering import (
    CoordinateFrame,
    DepthDirection,
    MeasuredDepthInterval,
    Unit,
)
from resinsight_mcp.contracts.errors import Error, ErrorCode, Failure, OperationResult, Success
from resinsight_mcp.contracts.identifiers import (
    ArtifactId,
    EditId,
    ObservationId,
)
from resinsight_mcp.contracts.jobs import Result
from resinsight_mcp.contracts.models import ArtifactRef, Session
from resinsight_mcp.contracts.observations import (
    Camera,
    EditedView,
    EditReceipt,
    ImageArtifact,
    Legend,
    Observation,
    PerforationEditRequest,
    Projection,
    Property,
    ViewContext,
)
from resinsight_mcp.contracts.sessions import ApplicationContext, ObjectKind, ObjectRef
from resinsight_mcp.contracts.workspace import Artifact, ArtifactKind
from resinsight_mcp.mcp.content import encode_result
from resinsight_mcp.workspaces import SqliteWorkspaceStore


@pytest.fixture
def view(context: ApplicationContext, result: Result) -> ViewContext:
    return ViewContext(
        model=result.model,
        result_id=result.result_id,
        grid_id=result.grid_id,
        case=ObjectRef(context=context, kind=ObjectKind.CASE, object_id="0"),
        view=ObjectRef(context=context, kind=ObjectKind.VIEW, object_id="1"),
        scene_version=2,
        property=Property(name="SGAS", unit=Unit.ONE),
        report_time=result.report_series.reports[-1],
        coordinates=CoordinateFrame(
            length_unit=Unit.FOOT,
            depth_direction=DepthDirection.POSITIVE_UP,
            datum="SPE1 local origin",
        ),
        camera=Camera(
            position=(20000.0, 20000.0, 0.0),
            target=(5000.0, 5000.0, -8375.0),
            up=(0.0, 0.0, 1.0),
            projection=Projection.ORTHOGRAPHIC,
            parallel_scale=10000.0,
        ),
        vertical_exaggeration=20.0,
        legend=Legend(minimum=0.0, maximum=1.0),
        filters=(),
    )


@pytest.fixture
def observation(view: ViewContext) -> Observation:
    return Observation(
        observation_id=ObservationId.new(),
        context=view,
        image=ImageArtifact(
            artifact=ArtifactRef(session_id=view.model.session_id, artifact_id=ArtifactId.new()),
            width=1280,
            height=900,
        ),
        captured_at=datetime(2026, 9, 8, 12, 12, tzinfo=UTC),
    )


@pytest.fixture
def receipt(view: ViewContext) -> EditReceipt:
    request = PerforationEditRequest(
        model=view.model,
        well=ObjectRef(context=view.view.context, kind=ObjectKind.WELL, object_id="P01IMPORT"),
        interval=MeasuredDepthInterval(start=8326.0, end=8424.0, unit=Unit.FOOT),
        expected_scene_version=1,
    )
    return EditReceipt(edit_id=EditId.new(), request=request, scene_version=2)


@pytest.fixture
def store(tmp_path: Path, observation: Observation) -> SqliteWorkspaceStore:
    store = SqliteWorkspaceStore.create(tmp_path / "workspace")
    assert isinstance(
        store.create_session(
            Session(session_id=observation.context.model.session_id, name="Image test")
        ).outcome,
        Success,
    )
    return store


def save_image(store: SqliteWorkspaceStore, observation: Observation, source: BytesIO) -> None:
    source.seek(0)
    written = store.write_artifact(
        Artifact(
            ref=observation.image.artifact, relative_path="frame.png", kind=ArtifactKind.IMAGE
        ),
        source,
    )
    assert isinstance(written.outcome, Success)


def image_source(size: tuple[int, int] = (1280, 900), format: str = "PNG") -> BytesIO:
    source = BytesIO()
    Image.new("RGB", size, "red").save(source, format=format)
    return source


def test_native_image_preserves_full_context(
    store: SqliteWorkspaceStore, observation: Observation
) -> None:
    save_image(store, observation, image_source())
    result = OperationResult[Observation](outcome=Success(value=observation))
    response = encode_result(result, store)
    assert response.isError is False
    text, image = response.content
    assert isinstance(text, TextContent)
    assert json.loads(text.text) == response.structuredContent == result.model_dump(mode="json")
    assert isinstance(image, ImageContent)
    assert image.mimeType == "image/png"
    assert image.annotations is None
    with Image.open(BytesIO(base64.b64decode(image.data))) as decoded:
        decoded.load()
        assert decoded.size == (1280, 900)
        assert decoded.format == "PNG"


@pytest.mark.parametrize("problem", ["empty", "corrupt", "dimensions", "format", "missing"])
def test_image_failure_returns_no_old_image(
    store: SqliteWorkspaceStore, observation: Observation, problem: str
) -> None:
    if problem != "missing":
        sources = {
            "empty": BytesIO(),
            "corrupt": BytesIO(b"This is not an image."),
            "dimensions": image_source((20, 10)),
            "format": image_source(format="JPEG"),
        }
        save_image(store, observation, sources[problem])
    response = encode_result(
        OperationResult[Observation](outcome=Success(value=observation)), store
    )
    assert response.isError is True
    assert len(response.content) == 1
    text = response.content[0]
    assert isinstance(text, TextContent)
    outcome = OperationResult[Observation].model_validate_json(text.text).outcome
    assert isinstance(outcome, Failure)
    expected = ErrorCode.NOT_FOUND if problem == "missing" else ErrorCode.RENDER_FAILED
    assert outcome.error.code == expected
    assert json.loads(text.text) == response.structuredContent
    assert "value" not in outcome.model_dump()


@pytest.mark.parametrize("valid_image", [True, False])
def test_applied_edit_survives_image_delivery_outcome(
    store: SqliteWorkspaceStore,
    observation: Observation,
    receipt: EditReceipt,
    valid_image: bool,
) -> None:
    save_image(store, observation, image_source() if valid_image else BytesIO())
    value = EditedView(
        edit=receipt, observation=OperationResult[Observation](outcome=Success(value=observation))
    )
    response = encode_result(OperationResult[EditedView](outcome=Success(value=value)), store)
    assert response.isError is False
    text = response.content[0]
    assert isinstance(text, TextContent)
    restored = OperationResult[EditedView].model_validate_json(text.text).outcome
    assert isinstance(restored, Success)
    assert restored.value.edit == receipt
    assert restored.value.edit.effect == "applied"
    assert isinstance(restored.value.observation.outcome, Success if valid_image else Failure)
    assert len(response.content) == (2 if valid_image else 1)


def test_failed_observation_preserves_applied_receipt(
    store: SqliteWorkspaceStore, receipt: EditReceipt
) -> None:
    value = EditedView(
        edit=receipt,
        observation=OperationResult[Observation](
            outcome=Failure(error=Error(code=ErrorCode.RENDER_FAILED, message="Render failed."))
        ),
    )
    result = OperationResult[EditedView](outcome=Success(value=value))
    response = encode_result(result, store)
    assert response.isError is False
    assert response.structuredContent == result.model_dump(mode="json")
    assert len(response.content) == 1


def test_other_results_preserve_success_and_stable_failure(store: SqliteWorkspaceStore) -> None:
    for result in (
        OperationResult[str](outcome=Success(value="Ready")),
        OperationResult[str](
            outcome=Failure(error=Error(code=ErrorCode.BUSY, message="The application is busy."))
        ),
    ):
        response = encode_result(result, store)
        assert response.isError == isinstance(result.outcome, Failure)
        assert response.structuredContent == result.model_dump(mode="json")
        assert len(response.content) == 1


def test_unexpected_image_read_failure_has_safe_error(
    store: SqliteWorkspaceStore, observation: Observation, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_read(artifact: ArtifactRef) -> None:
        raise OSError("Private workspace path must not reach the client.")

    monkeypatch.setattr(store, "open_artifact", fail_read)
    response = encode_result(
        OperationResult[Observation](outcome=Success(value=observation)), store
    )
    assert response.isError is True
    assert len(response.content) == 1
    text = response.content[0]
    assert isinstance(text, TextContent)
    outcome = OperationResult[Observation].model_validate_json(text.text).outcome
    assert isinstance(outcome, Failure)
    assert outcome.error.code == ErrorCode.RENDER_FAILED
    assert "Private workspace" not in text.text
