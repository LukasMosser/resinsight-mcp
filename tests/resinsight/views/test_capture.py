"""A capture publishes one new, decoded image with its exact view context."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image

from resinsight_mcp.contracts.errors import ContractError, ErrorCode
from resinsight_mcp.contracts.observations import ViewContext
from resinsight_mcp.contracts.workspace import ArtifactKind
from resinsight_mcp.resinsight.views._capture import capture
from resinsight_mcp.workspaces import SqliteWorkspaceStore

from .conftest import value


def export_png(folder: Path, width: int, height: int) -> None:
    Image.new("RGB", (width, height), "navy").save(folder / "native.png")


def test_capture_retains_context_and_distinct_decoded_images(
    store: SqliteWorkspaceStore, view_context: ViewContext
) -> None:
    started = datetime.now(UTC)
    first = capture(store, view_context, 64, 48, export_png)
    second = capture(store, view_context, 80, 60, export_png)
    assert first.observation_id != second.observation_id
    assert first.image.artifact != second.image.artifact
    artifacts = [value(store.get_artifact(item.image.artifact)) for item in (first, second)]
    assert artifacts[0].relative_path != artifacts[1].relative_path
    for observation, artifact, size in zip(
        (first, second), artifacts, ((64, 48), (80, 60)), strict=True
    ):
        retained = value(
            store.get_observation(view_context.model.session_id, observation.observation_id)
        )
        assert retained == observation
        assert retained.context == view_context
        assert started <= retained.captured_at <= datetime.now(UTC)
        assert retained.image.media_type == "image/png"
        assert (retained.image.width, retained.image.height) == size
        assert artifact.kind == ArtifactKind.IMAGE
        with store.open_artifact(retained.image.artifact) as source, Image.open(source) as image:
            image.load()
            assert image.format == "PNG"
            assert image.size == size


def test_missing_export_after_success_cannot_reuse_previous_image(
    store: SqliteWorkspaceStore, view_context: ViewContext
) -> None:
    previous = capture(store, view_context, 64, 48, export_png)
    artifacts = value(store.list_artifacts(view_context.model.session_id))

    def missing_export(folder: Path, width: int, height: int) -> None:
        assert not tuple(folder.iterdir())

    with pytest.raises(ContractError) as raised:
        capture(store, view_context, 64, 48, missing_export)
    assert raised.value.error.code == ErrorCode.RENDER_FAILED
    assert value(store.list_artifacts(view_context.model.session_id)) == artifacts
    assert (
        value(store.get_observation(view_context.model.session_id, previous.observation_id))
        == previous
    )


@pytest.mark.parametrize("failure", ["dimensions", "corrupt", "multiple"])
def test_invalid_export_does_not_publish_an_image(
    store: SqliteWorkspaceStore, view_context: ViewContext, failure: str
) -> None:
    artifacts = value(store.list_artifacts(view_context.model.session_id))

    def invalid_export(folder: Path, width: int, height: int) -> None:
        if failure == "corrupt":
            (folder / "native.png").write_text("The native export failed.")
        elif failure == "dimensions":
            export_png(folder, width + 1, height)
        else:
            export_png(folder, width, height)
            Image.new("RGB", (width, height)).save(folder / "second.png")

    with pytest.raises(ContractError) as raised:
        capture(store, view_context, 64, 48, invalid_export)
    assert raised.value.error.code == ErrorCode.RENDER_FAILED
    assert value(store.list_artifacts(view_context.model.session_id)) == artifacts
