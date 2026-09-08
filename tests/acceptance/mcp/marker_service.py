"""Serve a synthetic marker through the production transport and encoder."""

import argparse
import asyncio
import io
import json
import secrets
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from resinsight_mcp.contracts.engineering import (
    CoordinateFrame,
    DepthDirection,
    ModelRef,
    ReportTime,
    Unit,
)
from resinsight_mcp.contracts.errors import Error, ErrorCode, Failure, OperationResult, Success
from resinsight_mcp.contracts.identifiers import (
    ArtifactId,
    ConnectionId,
    GridId,
    ObservationId,
    ResultId,
    RevisionId,
    SessionId,
)
from resinsight_mcp.contracts.models import ArtifactRef, Session
from resinsight_mcp.contracts.observations import (
    Camera,
    ImageArtifact,
    Legend,
    Observation,
    Projection,
    Property,
    ViewContext,
)
from resinsight_mcp.contracts.sessions import ApplicationContext, ObjectKind, ObjectRef
from resinsight_mcp.contracts.workspace import Artifact, ArtifactKind
from resinsight_mcp.mcp import Bindings, serve_stdio
from resinsight_mcp.mcp import server as protocol
from resinsight_mcp.workspaces import SqliteWorkspaceStore


class MarkerStore(SqliteWorkspaceStore):
    """Use a synthetic observation with real stored image access."""

    observation: Observation

    def get_observation(
        self, session_id: SessionId, observation_id: ObservationId
    ) -> OperationResult[Observation]:
        if (session_id, observation_id) != (
            self.observation.context.model.session_id,
            self.observation.observation_id,
        ):
            return OperationResult(
                outcome=Failure(
                    error=Error(code=ErrorCode.NOT_FOUND, message="The observation was not found.")
                )
            )
        return OperationResult(outcome=Success(value=self.observation))


def prepare(
    evidence: Path, mode: str, session_id: SessionId, observation_id: ObservationId
) -> MarkerStore:
    """Keep random marker coordinates out of observation metadata."""
    row, column = secrets.randbelow(4) + 1, secrets.randbelow(4) + 1
    image = Image.new("RGB", (600, 600), "white")
    draw = ImageDraw.Draw(image)
    for index in range(5):
        offset = 60 + index * 120
        draw.line((60, offset, 540, offset), fill="black", width=3)
        draw.line((offset, 60, offset, 540), fill="black", width=3)
    x, y = column * 120, row * 120
    draw.ellipse((x - 30, y - 30, x + 30, y + 30), fill="red")
    image.save(evidence / "marker.png")
    (evidence / "witness.json").write_text(json.dumps({"row": row, "column": column}) + "\n")
    store = MarkerStore.create(evidence / "workspace")
    assert isinstance(store, MarkerStore)
    assert isinstance(
        store.create_session(Session(session_id=session_id, name="Synthetic marker")).outcome,
        Success,
    )
    ref = ArtifactRef(session_id=session_id, artifact_id=ArtifactId.new())
    source = io.BytesIO()
    if mode != "empty":
        image.save(source, format="PNG")
    source.seek(0)
    assert isinstance(
        store.write_artifact(
            Artifact(ref=ref, relative_path="marker.png", kind=ArtifactKind.IMAGE), source
        ).outcome,
        Success,
    )
    application = ApplicationContext(
        session_id=session_id, connection_id=ConnectionId.new(), project_generation=1
    )
    store.observation = Observation(
        observation_id=observation_id,
        context=ViewContext(
            model=ModelRef(session_id=session_id, revision_id=RevisionId.new()),
            result_id=ResultId.new(),
            grid_id=GridId.new(),
            case=ObjectRef(context=application, kind=ObjectKind.CASE, object_id="fixture"),
            view=ObjectRef(context=application, kind=ObjectKind.VIEW, object_id="fixture"),
            scene_version=1,
            property=Property(name="synthetic marker", unit=Unit.ONE),
            report_time=ReportTime(index=0, elapsed_days=0, calendar_date=datetime.now(UTC).date()),
            coordinates=CoordinateFrame(
                length_unit=Unit.METER,
                depth_direction=DepthDirection.POSITIVE_DOWN,
                datum="synthetic",
            ),
            camera=Camera(
                position=(0, 0, 1),
                target=(0, 0, 0),
                up=(0, 1, 0),
                projection=Projection.ORTHOGRAPHIC,
                parallel_scale=1,
            ),
            vertical_exaggeration=1,
            legend=Legend(minimum=0, maximum=1),
            filters=(),
        ),
        image=ImageArtifact(artifact=ref, width=600, height=600),
        captured_at=datetime.now(UTC),
    )
    return store


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--mode", choices=("visible", "empty", "hidden"), required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--observation-id", required=True)
    args = parser.parse_args()
    store = prepare(
        args.evidence, args.mode, SessionId(args.session_id), ObservationId(args.observation_id)
    )
    original = protocol.encode_result

    def record(result, workspaces):
        response = original(result, workspaces)
        if args.mode == "hidden":
            # TEST ONLY: remove native images while retaining production metadata.
            response.content = [item for item in response.content if item.type != "image"]
        (args.evidence / "server-content.json").write_text(response.model_dump_json() + "\n")
        return response

    with patch.object(protocol, "encode_result", record):
        asyncio.run(serve_stdio(Bindings(workspaces=store)))


if __name__ == "__main__":
    main()
