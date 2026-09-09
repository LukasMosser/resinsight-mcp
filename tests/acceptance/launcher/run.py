"""Exercise one real session through the installed, shipped MCP launcher.

The independent snapshot and final native shutdown are evidence and owned cleanup.
Neither operation supplies domain setup or claims MCP image delivery.
"""

import argparse
import asyncio
import json
import os
import platform
import shutil
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from importlib.metadata import distribution, version
from pathlib import Path
from typing import Any, cast
from xml.etree import ElementTree

import grpc
import psutil
import rips
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent, TextResourceContents
from PIL import Image
from rips.generated import App_pb2_grpc, Definitions_pb2

import resinsight_mcp
from resinsight_mcp.contracts.identifiers import SessionId
from resinsight_mcp.contracts.sessions import Connection, ProjectState
from resinsight_mcp.resinsight.sessions.rips import RipsApplicationFactory

WORKSPACE_TOOLS = {"session_create", "session_list", "session_get", "observation_get"}
SESSION_TOOLS = {
    "session_select",
    "connection_list",
    "connection_get",
    "application_launch",
    "application_attach",
    "application_close",
    "project_inspect",
    "project_open",
    "project_save",
    "project_close",
    "object_resolve",
}


def write_record(path: Path, record: Any) -> None:
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def check_project(path: Path) -> dict[str, Any]:
    """Check the archived project's external paths before opening it."""
    document = ElementTree.parse(path)
    assert document.getroot().tag == "ResInsightProject"
    references = []
    for record in document.findtext("ReferencedExternalFiles", "").split(";"):
        if not record.strip():
            continue
        key, name = record.strip().split(maxsplit=1)
        if key.endswith("_Name$"):
            continue
        source = Path(name)
        assert source.is_absolute() and source.exists(), source
        references.append({"key": key, "path": str(source), "is_file": source.is_file()})
        if source.suffix == ".EGRID":
            for suffix in (".INIT", ".UNRST", ".SMSPEC", ".UNSMRY"):
                assert source.with_suffix(suffix).is_file(), source.with_suffix(suffix)
    assert references
    return {"project": str(path), "references": references, "result": "all paths exist"}


class Trial:
    def __init__(self, output: Path, executable: Path, project: Path) -> None:
        self.output = output
        self.executable = executable.resolve()
        self.project = project
        self.logs = output / "native-logs"
        self.logs.mkdir()
        self.cwd = output / "client"
        self.cwd.mkdir()
        self.session_id = str(SessionId.new())
        self.original: Connection | None = None
        self.calls = 0

    def event(self, name: str, **details: Any) -> None:
        record = {"at": datetime.now(UTC).isoformat(), "event": name, **details}
        with (self.output / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record) + "\n")
        print(json.dumps(record), flush=True)

    @asynccontextmanager
    async def client(
        self, label: str, *, native: bool, create: bool = False
    ) -> AsyncIterator[ClientSession]:
        arguments = ["-m", "resinsight_mcp.mcp", "--workspace-root", str(self.output / "workspace")]
        if create:
            arguments.append("--create-workspace")
        if native:
            arguments.extend(["--resinsight-log-directory", str(self.logs)])
        environment = {
            key: value
            for key, value in os.environ.items()
            if key not in {"PYTHONPATH", "PYTHONHOME"}
        }
        parameters = StdioServerParameters(
            command=sys.executable, args=arguments, env=environment, cwd=self.cwd
        )
        self.event(
            "launcher_started",
            label=label,
            command=[sys.executable, *arguments],
            cwd=str(self.cwd),
            pythonpath=None,
            pythonhome=None,
            qt_plugin_path=environment.get("QT_PLUGIN_PATH"),
        )
        with (self.output / f"{label}-stderr.log").open("w") as errors:
            async with stdio_client(parameters, errlog=errors) as (read, write):
                async with ClientSession(
                    read, write, read_timeout_seconds=timedelta(seconds=180)
                ) as client:
                    initialized = await client.initialize()
                    self.event(
                        "mcp_initialized", label=label, response=initialized.model_dump(mode="json")
                    )
                    await self.discovery(client, native)
                    yield client
        self.event("mcp_disconnected", label=label)

    async def discovery(self, client: ClientSession, native: bool) -> None:
        tools = await client.list_tools()
        resources = await client.list_resources()
        resource = next(
            item for item in resources.resources if str(item.uri) == "resinsight://catalog"
        )
        catalog = await client.read_resource(resource.uri)
        content = catalog.contents[0]
        assert isinstance(content, TextResourceContents)
        expected = WORKSPACE_TOOLS | SESSION_TOOLS if native else WORKSPACE_TOOLS
        assert {tool.name for tool in tools.tools} == expected
        assert {item["name"] for item in json.loads(content.text)["tools"]} == expected
        self.event(
            "catalog_verified",
            native=native,
            tools=tools.model_dump(mode="json"),
            resources=resources.model_dump(mode="json"),
            catalog=catalog.model_dump(mode="json"),
        )

    async def call(
        self,
        client: ClientSession,
        name: str,
        arguments: dict[str, Any],
        *,
        error: str | None = None,
    ) -> dict[str, Any]:
        self.calls += 1
        self.event("tool_requested", index=self.calls, tool=name, arguments=arguments)
        response = await client.call_tool(name, arguments)
        self.event(
            "tool_completed", index=self.calls, tool=name, response=response.model_dump(mode="json")
        )
        content = response.content[0]
        assert isinstance(content, TextContent)
        record = json.loads(content.text)
        assert record == response.structuredContent
        outcome = record["outcome"]
        if error is not None:
            assert response.isError and outcome["status"] == "failure", record
            assert outcome["error"]["code"] == error, record
            return outcome["error"]
        assert not response.isError and outcome["status"] == "success", record
        return outcome["value"]

    def verify_origin(self, reason: str) -> psutil.Process:
        assert self.original is not None and self.original.process is not None
        identity = self.original.process
        process = psutil.Process(identity.pid)
        assert str(process.create_time()) == identity.start_marker
        assert process.is_running() and process.status() != psutil.STATUS_ZOMBIE
        command = process.cmdline()
        assert Path(process.exe()).resolve() == self.executable
        assert Path(command[0]).resolve() == self.executable
        assert command[1:3] == ["--server", "0"]
        assert command[3] == "--portnumberfile"
        port_file = Path(command[4])
        assert port_file.parent.resolve() == self.logs.resolve()
        assert int(port_file.read_text().strip()) == self.original.endpoint.port
        lsof = shutil.which("lsof")
        assert lsof is not None
        inspected = subprocess.run(
            [lsof, "-nP", f"-iTCP@127.0.0.1:{self.original.endpoint.port}", "-sTCP:LISTEN", "-Fp"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        listeners = {
            int(line[1:]) for line in inspected.stdout.splitlines() if line.startswith("p")
        }
        assert listeners == {identity.pid}
        self.event(
            "original_process_verified",
            reason=reason,
            identity=identity.model_dump(mode="json"),
            command=command,
            executable=process.exe(),
            endpoint=self.original.endpoint.model_dump(mode="json"),
            listener_output=inspected.stdout,
        )
        return process

    async def project_work(self, client: ClientSession) -> ProjectState:
        blank = await self.call(client, "project_inspect", {"session_id": self.session_id})
        opened = await self.call(
            client, "project_open", {"context": blank["context"], "path": str(self.project)}
        )
        project = ProjectState.model_validate_json(json.dumps(opened))
        assert {item.ref.kind.value for item in project.objects} >= {"case", "view"}
        for item in project.objects:
            resolved = await self.call(client, "object_resolve", item.ref.model_dump(mode="json"))
            assert resolved == item.model_dump(mode="json")
        destination = self.output / "saved-project.rsp"
        saved = await self.call(
            client,
            "project_save",
            {"context": opened["context"], "path": str(destination), "overwrite": False},
        )
        assert saved["last_saved_path"] == str(destination)
        assert saved["context"]["project_generation"] > opened["context"]["project_generation"]
        assert ElementTree.parse(destination).findtext("DocumentFileName") == str(destination)
        await self.call(
            client,
            "object_resolve",
            project.objects[0].ref.model_dump(mode="json"),
            error="stale_object",
        )
        closed = await self.call(client, "project_close", {"context": saved["context"]})
        assert not closed["objects"]
        reopened = await self.call(
            client, "project_open", {"context": closed["context"], "path": str(destination)}
        )
        assert reopened["context"]["project_generation"] > closed["context"]["project_generation"]
        assert {(item["ref"]["kind"], item["name"]) for item in reopened["objects"]} == {
            (item.ref.kind.value, item.name) for item in project.objects
        }
        return ProjectState.model_validate_json(json.dumps(reopened))

    def snapshot(self) -> None:
        """Observe the opened project independently, without editing its view."""
        self.verify_origin("before independent snapshot")
        assert self.original is not None
        folder = self.output / "images"
        folder.mkdir()
        with grpc.insecure_channel(
            f"127.0.0.1:{self.original.endpoint.port}", options=[("grpc.enable_http_proxy", False)]
        ) as channel:
            native = cast(Any, rips.Project).create(channel)
            views = native.views()
            assert views
            views[0].export_snapshot(export_folder=str(folder), width=1200, height=800)
            observed = App_pb2_grpc.AppStub(channel).GetVersion(Definitions_pb2.Empty(), timeout=30)
        pictures = list(folder.glob("*.png"))
        assert len(pictures) == 1
        with Image.open(pictures[0]) as picture:
            picture.load()
            assert picture.size == (1200, 800)
        self.event(
            "independent_snapshot",
            path=str(pictures[0]),
            dimensions=[1200, 800],
            native_version={"major": observed.major_version, "minor": observed.minor_version},
            mcp_image_delivery=False,
            view_edits=False,
        )

    async def reconnect(self, project: ProjectState) -> None:
        assert self.original is not None and self.original.process is not None
        self.verify_origin("after MCP disconnect")
        async with self.client("restarted", native=True) as client:
            await self.call(client, "session_get", {"session_id": self.session_id})
            await self.call(
                client, "connection_get", {"session_id": self.session_id}, error="not_found"
            )
            await self.call(
                client, "project_inspect", {"session_id": self.session_id}, error="not_found"
            )
            attached = await self.call(
                client,
                "application_attach",
                {
                    "session_id": self.session_id,
                    "endpoint": self.original.endpoint.model_dump(mode="json"),
                },
            )
            assert attached["ownership"] == "attached"
            assert attached["process"] == self.original.process.model_dump(mode="json")
            assert attached["context"]["connection_id"] != str(self.original.context.connection_id)
            current = await self.call(client, "project_inspect", {"session_id": self.session_id})
            assert {(item["ref"]["kind"], item["name"]) for item in current["objects"]} == {
                (item.ref.kind.value, item.name) for item in project.objects
            }
            await self.call(
                client,
                "object_resolve",
                project.objects[0].ref.model_dump(mode="json"),
                error="stale_object",
            )
            await self.call(
                client,
                "application_close",
                {
                    "session_id": self.session_id,
                    "connection_id": attached["context"]["connection_id"],
                    "action": "detach",
                },
            )
            detached = await self.call(client, "connection_get", {"session_id": self.session_id})
            assert detached["state"] == "detached"
        self.verify_origin("after explicit detach")

    async def run(self) -> None:
        async with self.client("workspace", native=False, create=True) as client:
            created = await self.call(
                client,
                "session_create",
                {"session_id": self.session_id, "name": "Shipped launcher trial"},
            )
            assert created["session_id"] == self.session_id
        async with self.client("native", native=True) as client:
            launched = await self.call(
                client,
                "application_launch",
                {"session_id": self.session_id, "executable": str(self.executable)},
            )
            self.original = Connection.model_validate_json(json.dumps(launched))
            assert self.original.ownership.value == "owned"
            self.verify_origin("after public launch")
            project = await self.project_work(client)
            self.snapshot()
        await self.reconnect(project)

    def cleanup(self) -> None:
        if self.original is None:
            self.event("cleanup_not_attempted", reason="No successful owned launch receipt exists.")
            return
        process = self.verify_origin("before graceful native cleanup")
        application = RipsApplicationFactory(self.logs).attach(self.original.endpoint)
        try:
            assert application.process == self.original.process
            application.terminate()
        finally:
            application.disconnect()
        assert not process.is_running()
        self.event(
            "cleanup_completed",
            process=self.original.process.model_dump(mode="json"),
            method="Verified native Exit after public detach",
            mcp_operation=False,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--native-commit", required=True)
    parser.add_argument("--native-build-record", type=Path, required=True)
    arguments = parser.parse_args()
    assert all(
        path.is_absolute() for path in (arguments.output, arguments.executable, arguments.project)
    )
    assert "PYTHONPATH" not in os.environ and "PYTHONHOME" not in os.environ
    package = Path(resinsight_mcp.__file__).resolve()
    assert "site-packages" in package.parts
    installed = distribution("resinsight-mcp")
    direct_url = json.loads(installed.read_text("direct_url.json") or "{}")
    assert not direct_url.get("dir_info", {}).get("editable", False)
    project_record = check_project(arguments.project)
    native_build = json.loads(arguments.native_build_record.read_text())
    assert (
        native_build["native_commit"] == arguments.native_commit and native_build["exit_code"] == 0
    )
    arguments.output.mkdir()
    write_record(arguments.output / "project-input.json", project_record)
    shutil.copyfile(arguments.native_build_record, arguments.output / "native-build.json")
    write_record(
        arguments.output / "environment.json",
        {
            "started_at": datetime.now(UTC).isoformat(),
            "command": sys.argv,
            "source_commit": arguments.source_commit,
            "native_commit": arguments.native_commit,
            "platform": platform.platform(),
            "python": sys.version,
            "executable": sys.executable,
            "package_path": str(package),
            "direct_url": direct_url,
            "versions": {
                name: version(name)
                for name in ("resinsight-mcp", "rips", "psutil", "mcp", "grpcio", "Pillow")
            },
            "working_directory": str(Path.cwd()),
            "pythonpath": None,
            "pythonhome": None,
            "qt_plugin_path": os.environ.get("QT_PLUGIN_PATH"),
        },
    )
    trial = Trial(arguments.output, arguments.executable, arguments.project)
    succeeded = False
    try:
        asyncio.run(trial.run())
        succeeded = True
    except BaseException as error:
        trial.event("acceptance_failed", error_type=type(error).__name__, message=str(error))
        raise
    finally:
        trial.cleanup()
        write_record(
            arguments.output / "result.json",
            {
                "passed": succeeded,
                "completed_tool_calls": trial.calls,
                "applications": 1,
                "mcp_images": 0,
                "independent_snapshots": 1 if succeeded else None,
                "native_editor_inspection": "Deferred under issue 34",
                "scope": "Shipped launcher session and project operations only",
            },
        )


if __name__ == "__main__":
    main()
