"""Prove model, well, run, result, and recovery behavior through public tools."""

from dataclasses import dataclass, field
from uuid import uuid4

from image_steps import Images
from job_steps import Jobs
from job_steps import reference as job_reference
from native_steps import Native
from numerical_checks import (
    check_fresh_connections,
    check_inspection,
    definitions,
    queries,
    reference,
)
from public_client import PublicClient, Record, write

REQUIRED = {
    "session_create",
    "session_list",
    "session_get",
    "session_select",
    "connection_get",
    "application_launch",
    "application_close",
    "project_inspect",
    "object_resolve",
    "project_save",
    "project_open",
    "project_close",
    "model_template",
    "model_create",
    "model_get",
    "model_inspect",
    "model_clone",
    "model_prepare",
    "model_load_case",
    "model_restore_case",
    "well_create",
    "well_inspect",
    "well_adopt",
    "well_export",
    "well_export_get",
    "model_publish_schedule",
    "job_submit",
    "job_poll",
    "job_cancel",
    "opm_collect",
    "result_get",
    "result_load",
    "result_rebind",
    "result_cell_property",
    "result_curve",
    "result_compare_cells",
    "result_compare_curves",
    "result_show_curve",
    "view_list",
    "view_apply",
    "view_render",
}


@dataclass
class Workflow:
    native: Native
    jobs: Jobs = field(default_factory=Jobs)
    foreign_id: str = field(default_factory=lambda: "session_" + uuid4().hex)
    specification: Record = field(default_factory=dict)
    inspection: Record = field(default_factory=dict)
    results: list[Record] = field(default_factory=list)
    numerical: list[Record] = field(default_factory=list)
    exports: dict[str, Record] = field(default_factory=dict)
    images: Images = field(init=False)
    old_well: Record = field(default_factory=dict)
    long_job: Record = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.images = Images(self.native)

    async def discovery(self, api: PublicClient) -> None:
        found = await api.discover()
        api.evidence.check(
            "public-workflow-catalog", REQUIRED <= found, missing=sorted(REQUIRED - found)
        )

    async def create(self, api: PublicClient) -> Record:
        await self.discovery(api)
        for session_id, name in (
            (self.native.session_id, "P13 baseline and scenario"),
            (self.foreign_id, "P13 isolated study"),
        ):
            await api.call("session_create", {"session_id": session_id, "name": name})
        sessions = await api.call("session_list", {})
        api.evidence.check(
            "two-named-sessions",
            {item["session_id"] for item in sessions} == {self.native.session_id, self.foreign_id},
        )
        self.specification = await api.call("model_template", {})
        created = await api.call(
            "model_create",
            {
                "session_id": self.native.session_id,
                "datum": "P13 local FIELD depth datum",
                "specification": self.specification,
            },
        )
        prepared = created["imported"]["prepared"]
        self.inspection = await api.call("model_inspect", prepared["revision"]["model"])
        check_inspection(api.evidence, self.specification, self.inspection)
        await api.call("session_select", {"session_id": self.foreign_id})
        await api.call(
            "model_get",
            prepared["revision"]["model"] | {"session_id": self.foreign_id},
            failure="not_found",
        )
        api.evidence.check(
            "selection-does-not-change-explicit-target",
            await api.call("model_get", prepared["revision"]["model"]) == prepared["revision"],
        )
        await self.native.launch(api)
        state = await self.native.project(api)
        await api.call(
            "model_load_case",
            {
                "context": state["context"] | {"session_id": self.foreign_id},
                "model": prepared["revision"]["model"],
            },
            failure="invalid_model",
        )
        await self.native.load_prepared(api, "original", prepared["revision"]["model"])
        intended = definitions(
            self.specification, self.inspection, prepared["revision"]["coordinates"]
        )
        await self.native.create_wells(api, "original", intended)
        self.exports = await self.native.exports(api, "baseline", self.specification)
        write(api.evidence.output / "public-specification.json", self.specification)
        return prepared

    async def publish(
        self, api: PublicClient, parent: Record, exports: dict[str, Record], *, scenario: bool
    ) -> Record:
        scheduled = []
        for well in self.specification["wells"]:
            control = well["control"]
            if scenario and control["kind"] == "producer":
                control = control | {
                    "oil_rate": control["oil_rate"] | {"value": control["oil_rate"]["value"] * 0.75}
                }
            scheduled.append(
                {
                    "export": exports[well["name"]]["artifact"],
                    "controls": [{"report_index": 0, "control": control}],
                }
            )
        published = await api.call("model_publish_schedule", {"parent": parent, "wells": scheduled})
        revision = published["prepared"]["revision"]
        api.evidence.check(
            "published-child-lineage", revision["parent"] == parent and revision["model"] != parent
        )
        return published["prepared"]

    async def initial(self, api: PublicClient) -> None:
        base = await self.create(api)
        baseline = await self.publish(api, base["revision"]["model"], self.exports, scenario=False)
        job, result = await self.jobs.run(api, "baseline", baseline)
        self.results.append(result)
        self.numerical.append(
            await queries(api, "baseline", result, self.specification, self.inspection)
        )
        await api.call(
            "job_poll", job_reference(job) | {"session_id": self.foreign_id}, failure="not_found"
        )
        loaded = await self.images.load(api, result, job)
        await self.images.baseline(api, loaded, self.numerical[0])
        self.old_well = self.native.wells["PROD"]["well"]
        await api.call("well_inspect", self.old_well, failure="stale_object")
        await self.native.restore(api, "original")
        cloned = await api.call(
            "model_clone",
            {"source": baseline["revision"]["model"], "revision_id": "revision_" + uuid4().hex},
        )
        api.evidence.check(
            "explicit-clone-lineage",
            cloned["parent"] == baseline["revision"]["model"]
            and cloned["inputs"] == baseline["revision"]["inputs"],
        )
        await self.native.load_prepared(api, "clone", cloned["model"])
        await self.native.adopt(api, "clone")
        changed_exports = await self.native.exports(api, "scenario", self.specification)
        for name in self.exports:
            api.evidence.check(
                f"{name}-clone-completions",
                changed_exports[name]["connections"] == self.exports[name]["connections"],
            )
        scenario = await self.publish(api, cloned["model"], changed_exports, scenario=True)
        job, result = await self.jobs.run(api, "scenario", scenario)
        self.results.append(result)
        self.numerical.append(
            await queries(api, "scenario", result, self.specification, self.inspection)
        )
        api.evidence.check(
            "distinct-run-identities",
            all(
                self.results[0][key] != result[key]
                for key in ("result_id", "job_id", "grid_id", "model")
            ),
        )
        await self.images.load(api, result, job)
        await self.images.compare(api, self.results, self.numerical, "comparison")
        await self.isolation(api)
        await self.project_reopen(api)

    async def isolation(self, api: PublicClient) -> None:
        for result in self.results:
            await api.call(
                "result_get",
                reference(result) | {"session_id": self.foreign_id},
                failure="not_found",
            )
        await api.call("connection_get", {"session_id": self.foreign_id}, failure="not_found")
        session = await api.call("session_get", {"session_id": self.foreign_id})
        api.evidence.check(
            "foreign-session-unchanged",
            session == {"session_id": self.foreign_id, "name": "P13 isolated study"},
        )

    async def recover(self, api: PublicClient, label: str) -> None:
        for name in self.native.prepared:
            await self.native.restore(api, name)
        await self.native.adopt(api, "clone")
        recovered = await self.native.exports(api, label, self.specification)
        for name, exported in self.exports.items():
            retained = await api.call("well_export_get", exported["artifact"])
            api.evidence.check(
                f"{label}-{name}-immutable-export",
                retained == exported,
            )
            check_fresh_connections(
                api.evidence,
                f"{label}-{name}",
                recovered[name]["connections"],
                exported["connections"],
            )
        await self.images.rebind(api, self.results)
        for index, result in enumerate(self.results):
            observed = await queries(
                api, f"{label}-{index}", result, self.specification, self.inspection
            )
            api.evidence.check(f"{label}-{index}-fresh-values", observed == self.numerical[index])
        await self.images.compare(api, self.results, self.numerical, label)

    async def project_reopen(self, api: PublicClient) -> None:
        path = api.evidence.output / "project-before-reopen.rsp"
        saved = await self.native.save(api, path)
        old = next(item["ref"] for item in saved["objects"] if item["ref"]["kind"] == "well")
        closed = await api.call("project_close", {"context": saved["context"]})
        await api.call("project_open", {"context": closed["context"], "path": str(path)})
        await api.call("well_inspect", old, failure="stale_object")
        await self.recover(api, "project-reopened")

    async def before_disconnect(self, api: PublicClient) -> None:
        await self.native.save(api, api.evidence.output / "project-before-disconnect.rsp")
        self.old_well = (await self.native.project(api))["objects"][0]["ref"]
        await self.native.close(api)
        specification = self.specification | {"report_intervals_days": [1] * 255}
        created = await api.call(
            "model_create",
            {
                "session_id": self.native.session_id,
                "datum": "P13 cancellation FIELD datum",
                "specification": specification,
            },
        )
        job = await self.jobs.submit(
            api, "disconnect-long", created["imported"]["prepared"], long=True
        )
        self.long_job = await self.jobs.poll(api, job, running=True)
        write(api.evidence.output / "job-before-disconnect.json", self.long_job)

    async def after_disconnect(self, api: PublicClient) -> None:
        current = await api.call("job_poll", job_reference(self.long_job))
        self.jobs.known[current["job_id"]] = current
        api.evidence.check(
            "running-job-survives-disconnect",
            current["state"] == "running"
            and current["container_id"] == self.long_job["container_id"]
            and current["submission"] == self.long_job["submission"],
        )
        write(api.evidence.output / "job-after-disconnect.json", current)
        await self.jobs.cancel(api, current)
        await self.discovery(api)
        await self.native.launch(api)
        await self.native.reopen(api, api.evidence.output / "project-before-disconnect.rsp")
        await api.call("object_resolve", self.old_well, failure="stale_object")
        await self.recover(api, "mcp-restarted")
        await self.isolation(api)
        await self.native.save(api, api.evidence.output / "accepted-project.rsp")
