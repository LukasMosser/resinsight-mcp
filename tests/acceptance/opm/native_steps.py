"""Use public references and receipts for every native application operation."""

from dataclasses import dataclass, field
from pathlib import Path

import psutil
from numerical_checks import check_definition, connection_table
from public_client import PublicClient, Record, TrialFailure, write


@dataclass
class Native:
    session_id: str
    executable: Path
    connection: Record | None = None
    prepared: dict[str, Record] = field(default_factory=dict)
    wells: dict[str, Record] = field(default_factory=dict)

    async def project(self, api: PublicClient) -> Record:
        return await api.call("project_inspect", {"session_id": self.session_id})

    async def launch(self, api: PublicClient) -> None:
        self.connection = await api.call(
            "application_launch",
            {"session_id": self.session_id, "executable": str(self.executable)},
        )
        api.evidence.check(
            "owned-native-launch",
            self.connection["ownership"] == "owned" and self.connection["process"] is not None,
        )
        write(
            api.evidence.output / f"native-{self.connection['context']['connection_id']}.json",
            self.connection,
        )

    async def close(self, api: PublicClient) -> None:
        if self.connection is None:
            return
        connection = await api.call("connection_get", {"session_id": self.session_id})
        api.evidence.check(
            "native-cleanup-identity",
            connection["process"] == self.connection["process"]
            and connection["ownership"] == "owned",
        )
        await api.call(
            "application_close",
            {
                "session_id": self.session_id,
                "connection_id": connection["context"]["connection_id"],
                "action": "terminate",
            },
        )
        identity = connection["process"]
        absent = not psutil.pid_exists(identity["pid"])
        if not absent:
            try:
                absent = (
                    str(psutil.Process(identity["pid"]).create_time()) != identity["start_marker"]
                )
            except psutil.NoSuchProcess:
                absent = True
        api.evidence.check("owned-native-lifetime-ended", absent, process=identity)
        self.connection = None

    async def load_prepared(self, api: PublicClient, label: str, model: Record) -> Record:
        state = await self.project(api)
        binding = await api.call("model_load_case", {"context": state["context"], "model": model})
        self.prepared[label] = binding
        return binding

    async def restore(self, api: PublicClient, label: str) -> Record:
        saved = self.prepared[label]
        state = await self.project(api)
        restored = await api.call(
            "model_restore_case",
            {"context": state["context"], "model": saved["model"], "receipt": saved["receipt"]},
        )
        api.evidence.check(
            f"{label}-prepared-receipt",
            restored["model"] == saved["model"] and restored["receipt"] == saved["receipt"],
        )
        self.prepared[label] = restored
        return restored

    async def well_reference(self, api: PublicClient, name: str) -> Record:
        state = await self.project(api)
        matches = [
            item["ref"]
            for item in state["objects"]
            if item["ref"]["kind"] == "well" and item["name"] == name
        ]
        if len(matches) != 1:
            raise TrialFailure(f"The current project must contain exactly one well named {name}.")
        return matches[0]

    async def create_wells(
        self, api: PublicClient, label: str, definitions: dict[str, Record]
    ) -> None:
        binding = self.prepared[label]
        for name, definition in definitions.items():
            created = await api.call("well_create", {"binding": binding, "definition": definition})
            self.wells[name] = created
            binding = created["binding"]
        self.prepared[label] = binding
        await self.inspect_wells(api)

    async def inspect_wells(self, api: PublicClient) -> None:
        for name, saved in tuple(self.wells.items()):
            observed = await api.call("well_inspect", await self.well_reference(api, name))
            check_definition(
                api.evidence, f"{name}-definition", observed["definition"], saved["definition"]
            )
            api.evidence.check(
                f"{name}-trajectory-retained", observed["trajectory"] == saved["trajectory"]
            )
            self.wells[name] = observed

    async def adopt(self, api: PublicClient, label: str) -> None:
        binding = self.prepared[label]
        for name, saved in tuple(self.wells.items()):
            adopted = await api.call(
                "well_adopt",
                {
                    "binding": binding,
                    "well": await self.well_reference(api, name),
                    "definition": saved["definition"],
                    "trajectory": saved["trajectory"],
                },
            )
            check_definition(
                api.evidence,
                f"{label}-{name}-definition",
                adopted["definition"],
                saved["definition"],
            )
            api.evidence.check(
                f"{label}-{name}-adopted",
                adopted["trajectory"] == saved["trajectory"] and adopted["version"] == 0,
            )
            self.wells[name] = adopted
            binding = adopted["binding"]
        self.prepared[label] = binding
        await self.inspect_wells(api)

    async def exports(
        self, api: PublicClient, label: str, specification: Record
    ) -> dict[str, Record]:
        await self.inspect_wells(api)
        exports = {}
        for spec in specification["wells"]:
            name = spec["name"]
            well = self.wells[name]
            exported = await api.call(
                "well_export", {"well": well["well"], "expected_version": well["version"]}
            )
            connection_table(api.evidence, f"{label}-{name}", exported, spec["cell"])
            exports[name] = exported
        write(api.evidence.output / f"{label}-exports.json", exports)
        return exports

    async def save(self, api: PublicClient, path: Path) -> Record:
        state = await self.project(api)
        return await api.call("project_save", {"context": state["context"], "path": str(path)})

    async def reopen(self, api: PublicClient, path: Path) -> None:
        state = await self.project(api)
        await api.call("project_open", {"context": state["context"], "path": str(path)})
