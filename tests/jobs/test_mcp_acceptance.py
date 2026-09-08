"""Disconnect and restart through real MCP client and server processes."""

import asyncio
import json
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

import psutil
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult, TextContent

from resinsight_mcp.contracts.errors import OperationResult
from resinsight_mcp.contracts.jobs import Job, JobRequest, JobState
from resinsight_mcp.jobs._common import require

from ._support import reference


@asynccontextmanager
async def client(root: Path, mode: str) -> AsyncIterator[ClientSession]:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(Path(__file__).with_name("mcp_server.py")), str(root), mode],
        env=dict(os.environ),
    )
    with (root / "mcp.log").open("a") as errors:
        async with stdio_client(parameters, errlog=errors) as (read, write):
            async with ClientSession(
                read, write, read_timeout_seconds=timedelta(seconds=10)
            ) as session:
                await session.initialize()
                yield session


def job_result(response: CallToolResult) -> Job:
    content = response.content[0]
    assert isinstance(content, TextContent) and not response.isError
    return require(OperationResult[Job].model_validate_json(content.text))


async def wait_state(session: ClientSession, job: Job, states: set[JobState]) -> Job:
    async with asyncio.timeout(10):
        while True:
            current = job_result(
                await session.call_tool("job_poll", reference(job).model_dump(mode="json"))
            )
            if current.state in states:
                return current
            assert current.state != JobState.UNKNOWN, current.model_dump_json()
            await asyncio.sleep(0.02)


@pytest.mark.parametrize("mode", ["complete", "cancel"])
def test_mcp_disconnect_restart_preserves_execution(
    workspace: tuple[Path, JobRequest], mode: str
) -> None:
    root, request = workspace

    async def exercise() -> Job:
        async with client(root, mode) as session:
            submitted = job_result(
                await session.call_tool("job_submit", request.model_dump(mode="json"))
            )
            running = await wait_state(session, submitted, {JobState.RUNNING})
            async with asyncio.timeout(5):
                while not (root / "ready").exists():
                    await asyncio.sleep(0.02)
        async with client(root, mode) as session:
            restored = job_result(
                await session.call_tool("job_poll", reference(submitted).model_dump(mode="json"))
            )
            assert restored.job_id == submitted.job_id and restored.model == submitted.model
            assert restored.process == running.process and restored.supervisor == running.supervisor
            assert restored.submission == submitted.submission
            assert restored.state == JobState.RUNNING
            if mode == "complete":
                (root / "release").touch()
                completed = await wait_state(session, submitted, {JobState.SUCCEEDED})
                assert (root / "executions.txt").read_text().splitlines() == ["started"]
            else:
                canceled = job_result(
                    await session.call_tool(
                        "job_cancel", reference(submitted).model_dump(mode="json")
                    )
                )
                assert canceled.cancel_requested
                completed = await wait_state(session, submitted, {JobState.CANCELED})
                assert completed.termination_confirmed
                child_pid = json.loads((root / "child.json").read_text())
                assert (
                    not psutil.pid_exists(child_pid)
                    or psutil.Process(child_pid).status() == psutil.STATUS_ZOMBIE
                )
            return completed

    completed = asyncio.run(exercise())
    print(f"MCP {mode} acceptance: {completed.model_dump_json()}")
