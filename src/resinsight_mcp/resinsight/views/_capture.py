"""Decode a fresh native export before publishing its observation."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from resinsight_mcp.contracts.errors import (
    ContractError,
    Error,
    ErrorCode,
    Failure,
    OperationResult,
)
from resinsight_mcp.contracts.identifiers import ArtifactId, ObservationId
from resinsight_mcp.contracts.interfaces import WorkspaceStore
from resinsight_mcp.contracts.models import ArtifactRef
from resinsight_mcp.contracts.observations import ImageArtifact, Observation, ViewContext
from resinsight_mcp.contracts.workspace import Artifact, ArtifactKind


def _value[T](result: OperationResult[T]) -> T:
    if isinstance(result.outcome, Failure):
        raise ContractError(result.outcome.error)
    return result.outcome.value


def _failure(message: str) -> ContractError:
    return ContractError(Error(code=ErrorCode.RENDER_FAILED, message=message))


def capture(
    store: WorkspaceStore,
    context: ViewContext,
    width: int,
    height: int,
    export: Callable[[Path, int, int], None],
) -> Observation:
    """Publish exactly one decoded PNG from a new export directory."""
    observation_id = ObservationId.new()
    try:
        with TemporaryDirectory(prefix="resinsight-observation-") as temporary:
            folder = Path(temporary)
            export(folder, width, height)
            images = tuple(folder.glob("*.png"))
            if len(images) != 1:
                raise _failure("The export must produce exactly one new PNG image.")
            path = images[0]
            with Image.open(path) as image:
                image.load()
                if image.format != "PNG" or image.size != (width, height):
                    raise _failure("The exported PNG dimensions differ from the request.")
            artifact = Artifact(
                ref=ArtifactRef(session_id=context.model.session_id, artifact_id=ArtifactId.new()),
                relative_path=f"observations/{observation_id}.png",
                kind=ArtifactKind.IMAGE,
            )
            with path.open("rb") as source:
                _value(store.write_artifact(artifact, source))
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        raise _failure("The new export could not be read and decoded.") from error
    observation = Observation(
        observation_id=observation_id,
        context=context,
        image=ImageArtifact(artifact=artifact.ref, width=width, height=height),
        captured_at=datetime.now(UTC),
    )
    return _value(store.save_observation(observation))
