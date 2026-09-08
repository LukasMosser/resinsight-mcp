"""Exercise public behavior through the SDK client and real subprocess transport."""

import asyncio
import json
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult, TextContent, TextResourceContents

from resinsight_mcp.contracts.errors import Success
from resinsight_mcp.contracts.identifiers import SessionId
from resinsight_mcp.contracts.jobs import Result
from resinsight_mcp.contracts.models import Session
from resinsight_mcp.workspaces import SqliteWorkspaceStore


@asynccontextmanager
async def client(
    root: Path, mode: str = "plain", observation_path: Path | None = None
) -> AsyncIterator[ClientSession]:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(Path(__file__).with_name("server_fixture.py")), str(root), mode]
        + ([str(observation_path)] if observation_path is not None else []),
        env={**os.environ},
    )
    with (root.parent / f"{mode}-stderr.log").open("w") as errors:
        async with stdio_client(parameters, errlog=errors) as (read, write):
            async with ClientSession(
                read, write, read_timeout_seconds=timedelta(seconds=10)
            ) as session:
                await session.initialize()
                yield session


def outcome(response: CallToolResult) -> dict[str, Any]:
    content = response.content[0]
    assert isinstance(content, TextContent)
    record = json.loads(content.text)
    assert response.structuredContent == record
    assert response.isError == (record["outcome"]["status"] == "failure")
    return record["outcome"]


def test_discovery_matches_resource_catalog(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    SqliteWorkspaceStore.create(root)

    async def exercise() -> None:
        async with client(root) as session:
            tools = (await session.list_tools()).tools
            by_name = {tool.name: tool for tool in tools}
            assert set(by_name) == {
                "session_create",
                "session_list",
                "session_get",
                "observation_get",
            }
            schema = by_name["session_get"].inputSchema
            assert schema["type"] == "object"
            assert schema["required"] == ["session_id"]
            assert schema["$defs"]["SessionId"]["type"] == "string"
            assert all(tool.outputSchema is not None for tool in tools)
            resources = (await session.list_resources()).resources
            assert [str(resource.uri) for resource in resources] == ["resinsight://catalog"]
            resource = await session.read_resource(resources[0].uri)
            content = resource.contents[0]
            assert isinstance(content, TextResourceContents)
            catalog = json.loads(content.text)
            assert {item["name"] for item in catalog["tools"]} == set(by_name)
            for item in catalog["tools"]:
                assert item["inputSchema"] == by_name[item["name"]].inputSchema
                assert item["outputSchema"] == by_name[item["name"]].outputSchema

    asyncio.run(exercise())


def test_explicit_sessions_survive_reconnect(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    store = SqliteWorkspaceStore.create(root)
    records = [Session(session_id=SessionId.new(), name=name) for name in ("First", "Second")]

    async def exercise() -> None:
        async with client(root) as session:
            for record in records:
                response = await session.call_tool("session_create", record.model_dump(mode="json"))
                assert outcome(response)["value"] == record.model_dump(mode="json")
            invalid = outcome(await session.call_tool("session_get", {}))
            assert invalid["error"]["code"] == "invalid_model"
            unknown = outcome(
                await session.call_tool("session_get", {"session_id": str(SessionId.new())})
            )
            assert unknown["error"]["code"] == "not_found"
        async with client(root) as session:
            listed = outcome(await session.call_tool("session_list", {}))["value"]
            assert {item["session_id"] for item in listed} == {
                str(record.session_id) for record in records
            }
            for record in reversed(records):
                fetched = outcome(
                    await session.call_tool("session_get", {"session_id": str(record.session_id)})
                )
                assert fetched["value"] == record.model_dump(mode="json")

    asyncio.run(exercise())
    assert isinstance(store.list_sessions().outcome, Success)


@pytest.mark.parametrize(
    ("mode", "code", "effect"),
    [("contract", "busy", "not_applied"), ("broken", "execution_failed", "not_applied")],
)
def test_service_errors_are_stable_and_sanitized(
    tmp_path: Path, mode: str, code: str, effect: str
) -> None:
    root = tmp_path / "workspace"
    SqliteWorkspaceStore.create(root)

    async def exercise() -> None:
        async with client(root, mode) as session:
            response = await session.call_tool("session_list", {})
            failure = outcome(response)
            assert failure["error"]["code"] == code
            assert failure["error"]["effect"] == effect
            assert "private-service-secret" not in response.model_dump_json()
            if mode == "contract":
                assert failure["error"]["message"] == "The workspace is busy."
            if mode == "broken":
                created = await session.call_tool(
                    "session_create",
                    {
                        "session_id": str(SessionId.new()),
                        "name": "Failed mutation",
                    },
                )
                mutation = outcome(created)
                assert mutation["error"]["code"] == "execution_failed"
                assert mutation["error"]["effect"] == "unknown"
                assert "private-service-secret" not in created.model_dump_json()
            unknown = outcome(await session.call_tool("unknown_tool", {}))
            assert unknown["error"]["code"] == "unsupported_operation"

    asyncio.run(exercise())


def test_service_output_stays_off_protocol_stdout(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    store = SqliteWorkspaceStore.create(root)
    record = Session(session_id=SessionId.new(), name="Noisy service")
    assert isinstance(store.create_session(record).outcome, Success)

    async def exercise() -> None:
        async with client(root, "noisy") as session:
            response = await session.call_tool(
                "session_get", {"session_id": str(record.session_id)}
            )
            assert outcome(response)["value"] == record.model_dump(mode="json")
            assert outcome(await session.call_tool("session_list", {}))["status"] == "success"

    asyncio.run(exercise())
    errors = (tmp_path / "noisy-stderr.log").read_text()
    assert "fixture service print" in errors
    assert "fixture service log" in errors
    assert "fixture child output" in errors


def test_image_response_preserves_context_and_decodes_png(tmp_path: Path, result: Result) -> None:
    from base64 import b64decode
    from datetime import UTC, datetime
    from io import BytesIO

    from mcp.types import ImageContent
    from PIL import Image

    from resinsight_mcp.contracts.engineering import (
        CoordinateFrame,
        DepthDirection,
        Unit,
        UnitSystem,
    )
    from resinsight_mcp.contracts.identifiers import ArtifactId, ConnectionId, ObservationId
    from resinsight_mcp.contracts.jobs import Job, JobState
    from resinsight_mcp.contracts.models import ArtifactRef, Backend, ModelInputs, ModelRevision
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

    root = tmp_path / "workspace"
    store = SqliteWorkspaceStore.create(root)
    owner = Session(session_id=result.model.session_id, name="Image owner")
    other = Session(session_id=SessionId.new(), name="Other workspace")
    for record in (owner, other):
        assert isinstance(store.create_session(record).outcome, Success)
    source = Artifact(
        ref=ArtifactRef(session_id=owner.session_id, artifact_id=ArtifactId.new()),
        relative_path="input.json",
        kind=ArtifactKind.INPUT,
    )
    assert isinstance(store.write_artifact(source, BytesIO(b"{} ")).outcome, Success)
    coordinates = CoordinateFrame(
        length_unit=Unit.METER, depth_direction=DepthDirection.POSITIVE_DOWN, datum="Local origin"
    )
    revision = ModelRevision(
        model=result.model,
        inputs=ModelInputs(artifacts=(source.ref.artifact_id,), entrypoint=source.ref.artifact_id),
        unit_system=UnitSystem.METRIC,
        coordinates=coordinates,
    )
    assert isinstance(store.save_revision(revision).outcome, Success)
    job = Job(
        job_id=result.job_id, model=result.model, backend=Backend.OPM_FLOW, state=JobState.QUEUED
    )
    assert isinstance(store.save_job(job).outcome, Success)
    queued = job
    job = queued.transition(JobState.RUNNING)
    assert isinstance(store.save_job(job, expected=queued).outcome, Success)
    done = job.transition(JobState.SUCCEEDED, exit_code=0)
    assert isinstance(store.save_job(done, expected=job).outcome, Success)
    assert isinstance(store.save_result(result).outcome, Success)
    active = Job(
        job_id=type(job.job_id).new(),
        model=result.model,
        backend=Backend.OPM_FLOW,
        state=JobState.QUEUED,
    )
    assert isinstance(store.save_job(active).outcome, Success)
    queued_active = active
    active = queued_active.transition(JobState.RUNNING)
    assert isinstance(store.save_job(active, expected=queued_active).outcome, Success)
    application = ApplicationContext(
        session_id=owner.session_id, connection_id=ConnectionId.new(), project_generation=1
    )
    view = ViewContext(
        model=result.model,
        result_id=result.result_id,
        grid_id=result.grid_id,
        case=ObjectRef(context=application, kind=ObjectKind.CASE, object_id="0"),
        view=ObjectRef(context=application, kind=ObjectKind.VIEW, object_id="1"),
        scene_version=3,
        property=Property(name="SGAS", unit=Unit.ONE),
        report_time=result.report_series.reports[-1],
        coordinates=coordinates,
        camera=Camera(
            position=(1, 1, 1),
            target=(0, 0, 0),
            up=(0, 0, 1),
            projection=Projection.ORTHOGRAPHIC,
            parallel_scale=100,
        ),
        vertical_exaggeration=2,
        legend=Legend(minimum=0, maximum=1),
        filters=(),
    )
    artifact = Artifact(
        ref=ArtifactRef(session_id=owner.session_id, artifact_id=ArtifactId.new()),
        relative_path="frame.png",
        kind=ArtifactKind.IMAGE,
    )
    pixels = BytesIO()
    Image.new("RGB", (32, 24), color="navy").save(pixels, format="PNG")
    pixels.seek(0)
    assert isinstance(store.write_artifact(artifact, pixels).outcome, Success)
    observation = Observation(
        observation_id=ObservationId.new(),
        context=view,
        image=ImageArtifact(artifact=artifact.ref, width=32, height=24),
        captured_at=datetime.now(UTC),
    )
    assert isinstance(store.save_observation(observation).outcome, Success)

    observation_path = tmp_path / "observation.json"
    observation_path.write_text(observation.model_dump_json())

    async def exercise() -> None:
        async with client(root, "render", observation_path) as session:
            assert "view_render" in {tool.name for tool in (await session.list_tools()).tools}
            rendered = await session.call_tool(
                "view_render",
                {
                    "session_id": str(owner.session_id),
                    "context": view.model_dump(mode="json"),
                    "width": 32,
                    "height": 24,
                },
            )
            assert outcome(rendered)["value"] == observation.model_dump(mode="json")
            assert any(isinstance(item, ImageContent) for item in rendered.content)
        for _ in range(2):
            async with client(root) as session:
                response = await session.call_tool(
                    "observation_get",
                    {
                        "session_id": str(owner.session_id),
                        "observation_id": str(observation.observation_id),
                    },
                )
                assert outcome(response)["value"] == observation.model_dump(mode="json")
                images = [item for item in response.content if isinstance(item, ImageContent)]
                assert len(images) == 1
                assert images[0].mimeType == "image/png"
                with Image.open(BytesIO(b64decode(images[0].data))) as decoded:
                    decoded.load()
                    assert decoded.format == "PNG"
                    assert decoded.size == (32, 24)
                denied = outcome(
                    await session.call_tool(
                        "observation_get",
                        {
                            "session_id": str(other.session_id),
                            "observation_id": str(observation.observation_id),
                        },
                    )
                )
                assert denied["error"]["code"] == "not_found"
        jobs = store.list_jobs(owner.session_id)
        assert isinstance(jobs.outcome, Success)
        assert active in jobs.outcome.value

    asyncio.run(exercise())
