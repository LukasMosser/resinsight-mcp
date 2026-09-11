"""Record the real SDK boundary without composing or importing domain services."""

import base64
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import ImageContent, TextResourceContents
from PIL import Image

type Record = dict[str, Any]


def write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


class TrialFailure(RuntimeError):
    """A recorded public outcome does not satisfy the acceptance requirement."""


@dataclass
class Evidence:
    output: Path
    calls: int = 0
    checks: list[Record] = field(default_factory=list)

    def check(self, name: str, passed: bool, **details: Any) -> None:
        self.checks.append({"name": name, "passed": passed, **details})
        write(self.output / "checks.json", self.checks)
        if not passed:
            raise TrialFailure(name)

    def event(self, name: str, **details: Any) -> None:
        with (self.output / "events.jsonl").open("a") as stream:
            stream.write(
                json.dumps({"at": datetime.now(UTC).isoformat(), "event": name, **details})
            )
            stream.write("\n")


@dataclass
class PublicClient:
    client: ClientSession
    evidence: Evidence

    async def call(
        self, name: str, request: Record, *, failure: str | None = None, image: bool = False
    ) -> Any:
        self.evidence.calls += 1
        stem = f"{self.evidence.calls:04d}-{name}"
        folder = self.evidence.output / "calls"
        write(folder / f"{stem}-request.json", {"name": name, "arguments": request})
        self.evidence.event("request", sequence=self.evidence.calls, tool=name)
        response = await self.client.call_tool(name, request)
        write(folder / f"{stem}-response.json", response.model_dump(mode="json"))
        content = response.structuredContent
        if content is None:
            raise TrialFailure(f"{name} returned no structured response.")
        outcome = content["outcome"]
        images = [item for item in response.content if isinstance(item, ImageContent)]
        for index, item in enumerate(images):
            data = base64.b64decode(item.data, validate=True)
            with Image.open(BytesIO(data)) as decoded:
                decoded.load()
                self.evidence.check(
                    f"{stem}-png-{index}",
                    decoded.format == "PNG" and item.mimeType == "image/png",
                    size=list(decoded.size),
                )
            (folder / f"{stem}-{index}.png").write_bytes(data)
        if failure is not None:
            self.evidence.check(
                f"{stem}-expected-failure",
                response.isError is True
                and outcome["status"] == "failure"
                and outcome["error"]["code"] == failure
                and not images,
                outcome=outcome,
            )
            return outcome
        if response.isError or outcome["status"] != "success":
            raise TrialFailure(f"{name} failed: {outcome}")
        result = outcome["value"]
        if image:
            observation = result.get("observation", {}).get("outcome", {})
            self.evidence.check(
                f"{stem}-fresh-image", len(images) == 1 and observation.get("status") == "success"
            )
            actual = observation["value"]["image"]
            with Image.open(folder / f"{stem}-0.png") as decoded:
                self.evidence.check(
                    f"{stem}-image-dimensions",
                    list(decoded.size) == [actual["width"], actual["height"]],
                )
        return result

    async def discover(self) -> set[str]:
        listed = await self.client.list_tools()
        write(
            self.evidence.output / f"catalog-{self.evidence.calls}.json",
            listed.model_dump(mode="json"),
        )
        resources = await self.client.list_resources()
        write(
            self.evidence.output / f"resources-{self.evidence.calls}.json",
            resources.model_dump(mode="json"),
        )
        catalog = next(
            item for item in resources.resources if str(item.uri) == "resinsight://catalog"
        )
        resource = await self.client.read_resource(catalog.uri)
        write(
            self.evidence.output / f"catalog-resource-{self.evidence.calls}.json",
            resource.model_dump(mode="json"),
        )
        records = [item for item in resource.contents if isinstance(item, TextResourceContents)]
        self.evidence.check("catalog-resource", len(records) == 1)
        described = json.loads(records[0].text)
        names = {item.name for item in listed.tools}
        self.evidence.check(
            "catalog-agreement", names == {item["name"] for item in described["tools"]}
        )
        self.evidence.check(
            "job-schema-has-no-command",
            set(
                next(item for item in listed.tools if item.name == "job_submit").inputSchema[
                    "properties"
                ]
            )
            == {"prepared", "limits", "resource_policy"},
        )
        return names


@asynccontextmanager
async def connect(
    arguments: Any, evidence: Evidence, *, create: bool
) -> AsyncIterator[PublicClient]:
    options = [
        "-I",
        "-m",
        "resinsight_mcp.mcp",
        "--workspace-root",
        str(arguments.output / "workspace"),
        "--enable-opm-workflow",
        "--resinsight-log-directory",
        str(arguments.output / "native-logs"),
        "--docker-executable",
        str(arguments.docker),
    ]
    if create:
        options.append("--create-workspace")
    environment = {
        name: value for name, value in os.environ.items() if not name.startswith("PYTHON")
    }
    parameters = StdioServerParameters(command=str(arguments.python), args=options, env=environment)
    evidence.event("launcher-start", command=parameters.command, arguments=options, create=create)
    with (arguments.output / "launcher-stderr.log").open("a") as errors:
        async with stdio_client(parameters, errlog=errors) as (read, send):
            async with ClientSession(
                read, send, read_timeout_seconds=timedelta(seconds=180)
            ) as session:
                initialized = await session.initialize()
                evidence.event("launcher-ready", initialize=initialized.model_dump(mode="json"))
                yield PublicClient(session, evidence)
    evidence.event("launcher-disconnected")
