"""Observe genuine collected results through one owned ResInsight application."""

import argparse
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime, time, timedelta
from importlib.metadata import distribution, version
from pathlib import Path
from typing import Any, cast

import rips
from pydantic import BaseModel

from resinsight_mcp.contracts.errors import Failure, OperationResult, Success
from resinsight_mcp.contracts.identifiers import ArtifactId, CheckpointId, ResultId, SessionId
from resinsight_mcp.contracts.jobs import JobRef, LoadedResult, Result, ResultImportRequest
from resinsight_mcp.contracts.models import ArtifactRef
from resinsight_mcp.contracts.observations import Property, ViewContext, ViewUpdateRequest
from resinsight_mcp.contracts.results import ResultDataset
from resinsight_mcp.contracts.sessions import (
    CloseAction,
    CloseRequest,
    LaunchRequest,
    ObjectKind,
    ProjectCloseRequest,
    ProjectOpenRequest,
    ProjectSaveRequest,
    ProjectState,
)
from resinsight_mcp.contracts.workspace import Artifact, ArtifactKind, ProjectCheckpoint
from resinsight_mcp.resinsight.sessions import ResInsightSessionService
from resinsight_mcp.resinsight.sessions.rips import RipsApplication, RipsApplicationFactory
from resinsight_mcp.resinsight.views import ResInsightViewService
from resinsight_mcp.resinsight.views._camera import read_camera
from resinsight_mcp.resinsight.views.rips import RipsViewBackend
from resinsight_mcp.results import (
    CellQuery,
    CurveQuery,
    ResultRef,
    ResultsService,
    SummaryPlotRequest,
)
from resinsight_mcp.results.rips import RipsResultBackend
from resinsight_mcp.simulators.opm import OpmFlowService
from resinsight_mcp.workspaces import SqliteWorkspaceStore


def value[T](result: OperationResult[T]) -> T:
    assert isinstance(result.outcome, Success), result.model_dump_json()
    return result.outcome.value


def record(path: Path, data: BaseModel | dict[str, Any]) -> None:
    content = data.model_dump(mode="json") if isinstance(data, BaseModel) else data
    path.write_text(json.dumps(content, indent=2, allow_nan=False) + "\n")


def export_artifact(store: SqliteWorkspaceStore, ref: ArtifactRef, destination: Path) -> None:
    with store.open_artifact(ref) as source, destination.open("xb") as target:
        shutil.copyfileobj(source, target)


def result_ref(result: Result) -> ResultRef:
    return ResultRef(session_id=result.model.session_id, result_id=result.result_id)


def source_dataset(store: SqliteWorkspaceStore, result: Result) -> ResultDataset:
    assert result.manifest is not None
    with store.open_artifact(result.manifest.numerical_data) as source:
        return ResultDataset.model_validate_json(source.read())


def native_evidence(
    sessions: ResInsightSessionService,
    loaded: LoadedResult,
    dataset: ResultDataset,
    output: Path,
) -> None:
    """Retain raw observations after the production verifier accepts the native case."""
    with sessions.access_objects((loaded.case,)) as access:
        application = cast(RipsApplication, access.application)
        project = cast(Any, application.project())
        case = next(
            item for item in project.cases() if str(item.address()) == access.objects[0].address
        )
        dimensions = case.grid().dimensions()
        corners = case.active_cell_corners()
        raw = [
            [[point.x, point.y, point.z] for point in [getattr(row, f"c{i}") for i in range(8)]]
            for row in corners
        ]
        ordered = [[row[i] for i in (0, 1, 3, 2, 4, 5, 7, 6)] for row in raw]
        differences = [
            [
                [a - b for a, b in zip(point, wanted, strict=True)]
                for point, wanted in zip(row, reference, strict=True)
            ]
            for row, reference in zip(ordered, dataset.geometry.cell_corners, strict=True)
        ]
        arrays = []
        for prop in dataset.cell_properties:
            for report, expected in zip(dataset.report_series.reports, prop.values, strict=True):
                observed = list(
                    case.active_cell_property("DYNAMIC_NATIVE", prop.name, report.index)
                )
                arrays.append(
                    {
                        "property": prop.name,
                        "source_unit": prop.unit,
                        "report": report.model_dump(mode="json"),
                        "source": expected,
                        "native": observed,
                        "differences": [a - b for a, b in zip(observed, expected, strict=True)],
                    }
                )
        summary = next(
            item
            for item in project.summary_cases()
            if Path(item.summary_header_filename) == Path(case.file_path).with_suffix(".SMSPEC")
        )
        stamps = list(summary.available_time_steps().values)
        indices = [
            stamps.index(
                round(
                    (
                        datetime.combine(report.calendar_date, time(), UTC)
                        + timedelta(days=report.elapsed_days % 1)
                    ).timestamp()
                )
            )
            for report in dataset.report_series.reports
        ]
        curves = []
        for curve in dataset.curves:
            address = (
                curve.keyword if curve.scope == "field" else f"{curve.keyword}:{curve.well_name}"
            )
            raw_values = list(summary.summary_vector_values(address).values)
            observed = [raw_values[index] for index in indices]
            curves.append(
                {
                    "address": address,
                    "source_unit": curve.unit,
                    "source": curve.values,
                    "native_all_samples": raw_values,
                    "native_report_values": observed,
                    "differences": [a - b for a, b in zip(observed, curve.values, strict=True)],
                }
            )
        record(
            output,
            {
                "result": loaded.result.model_dump(mode="json"),
                "case_path": case.file_path,
                "case_name": case.name,
                "native_dimensions": [dimensions.i, dimensions.j, dimensions.k],
                "native_active_cells": [
                    [item.grid_index, item.local_ijk.i, item.local_ijk.j, item.local_ijk.k]
                    for item in case.cell_info_for_active_cells()
                ],
                "native_elapsed_days": list(case.days_since_start()),
                "native_dates": [[day.year, day.month, day.day] for day in case.time_steps()],
                "source_geometry": dataset.geometry.model_dump(mode="json"),
                "native_corners": raw,
                "native_corners_opm_order": ordered,
                "corner_differences": differences,
                "cell_arrays": arrays,
                "curves": curves,
                "summary_timestamps": stamps,
                "summary_report_indices": indices,
                "unit_evidence": "P11 reads source units. RIPS has no independent unit getter.",
            },
        )


def capture_pair(
    store: SqliteWorkspaceStore,
    sessions: ResInsightSessionService,
    views: ResInsightViewService,
    results: ResultsService,
    loaded: tuple[LoadedResult, ...],
    output: Path,
) -> None:
    project = value(sessions.inspect_project(loaded[0].result.model.session_id))
    view_refs = tuple(obj.ref for obj in project.objects if obj.ref.kind == ObjectKind.VIEW)
    with sessions.access_objects(view_refs) as access:
        view_addresses = {
            native.address: ref for ref, native in zip(view_refs, access.objects, strict=True)
        }
    contexts: dict[ResultId, ViewContext] = {}
    common_camera = None
    for name in ("PRESSURE", "SWAT"):
        queries = [
            CellQuery(
                result=result_ref(item.result),
                property=name,
                report_time=item.result.report_series.reports[-1],
            )
            for item in loaded
        ]
        comparison = value(results.compare_cells(*queries))
        record(output / f"{name.lower()}-comparison.json", comparison)
        for label, item, values in zip(
            ("baseline", "scenario"),
            loaded,
            (comparison.baseline, comparison.scenario),
            strict=True,
        ):
            with sessions.access_objects((item.case,)) as access:
                application = cast(RipsApplication, access.application)
                native = cast(Any, application.project())
                case = next(
                    case
                    for case in native.cases()
                    if str(case.address()) == access.objects[0].address
                )
                view = next(
                    view for view in native.views() if view.case().address() == case.address()
                )
                address = str(view.address())
                if common_camera is None:
                    common_camera = read_camera(
                        view.camera_matrix,
                        view.camera_point_of_interest,
                        view.perspective_projection,
                        view.actual_camera_field_of_view_y_degrees,
                        view.actual_camera_parallel_projection_height,
                    )
                view_ref = view_addresses[address]
            previous = contexts.get(item.result.result_id)
            context = ViewContext(
                model=item.result.model,
                result_id=item.result.result_id,
                grid_id=item.result.grid_id,
                case=item.case,
                view=view_ref,
                scene_version=0 if previous is None else previous.scene_version,
                property=Property(name=name, unit=values.unit),
                report_time=values.report_time,
                coordinates=values.geometry.coordinates,
                camera=common_camera,
                vertical_exaggeration=1,
                legend=comparison.legend,
                filters=(),
            )
            edited = value(views.apply(ViewUpdateRequest(context=context, width=1200, height=800)))
            observation = value(edited.observation)
            contexts[item.result.result_id] = observation.context
            record(output / f"{label}-{name.lower()}.json", observation)
            export_artifact(
                store, observation.image.artifact, output / f"{label}-{name.lower()}.png"
            )


def checkpoint_trial(
    store: SqliteWorkspaceStore,
    sessions: ResInsightSessionService,
    results: ResultsService,
    loaded: tuple[LoadedResult, ...],
    output: Path,
) -> tuple[LoadedResult, ...]:
    baseline = loaded[0].result
    state = value(sessions.inspect_project(baseline.model.session_id))
    path = output / "results.rsp"
    saved = value(sessions.save_project(ProjectSaveRequest(context=state.context, path=path)))
    artifact = Artifact(
        ref=ArtifactRef(session_id=baseline.model.session_id, artifact_id=ArtifactId.new()),
        relative_path=f"p12/{output.name}/results.rsp",
        kind=ArtifactKind.PROJECT,
    )
    with path.open("rb") as source:
        value(store.write_artifact(artifact, source))
    checkpoint = value(
        store.save_checkpoint(
            ProjectCheckpoint(
                checkpoint_id=CheckpointId.new(),
                name="P12 baseline and scenario",
                model=baseline.model,
                project=artifact.ref,
                result_ids=tuple(item.result.result_id for item in loaded),
            )
        )
    )
    closed = value(sessions.close_project(ProjectCloseRequest(context=saved.context)))
    path.unlink()
    export_artifact(store, checkpoint.project, path)
    opened = value(sessions.open_project(ProjectOpenRequest(context=closed.context, path=path)))
    stale = sessions.resolve_object(loaded[0].case)
    assert isinstance(stale.outcome, Failure), "A pre-open reference remained valid."
    restored = value(results.restore(opened.context, checkpoint.checkpoint_id))
    assert tuple(item.result for item in restored) == tuple(item.result for item in loaded)
    assert all(item.case.context == opened.context for item in restored)
    record(output / "checkpoint.json", checkpoint)
    record(output / "stale-reference.json", stale)
    record(
        output / "restored.json", {"bindings": [item.model_dump(mode="json") for item in restored]}
    )
    return restored


def plot_inventory(sessions: ResInsightSessionService, state: ProjectState) -> dict[str, Any]:
    with sessions.access_objects(tuple(item.ref for item in state.objects)) as access:
        application = cast(RipsApplication, access.application)
        project = cast(Any, application.project())
        plots = []
        for plot in project.descendants(rips.SummaryPlot):
            parent = plot.ancestor(rips.MultiPlot)
            plots.append(
                {
                    "address": str(plot.address()),
                    "parent_window_id": None if parent is None else parent.id,
                }
            )
        return {"context": state.context.model_dump(mode="json"), "plots": plots}


def trial(arguments: argparse.Namespace) -> None:
    output = arguments.output.resolve()
    output.mkdir(exist_ok=False)
    store = SqliteWorkspaceStore.open(arguments.workspace)
    baseline, scenario = [
        value(store.get_result(arguments.session, item))
        for item in (arguments.baseline, arguments.scenario)
    ]
    assert baseline.model != scenario.model and baseline.job_id != scenario.job_id
    revision = value(store.get_revision(scenario.model))
    assert revision.parent == baseline.model, "The scenario must retain its baseline parent."
    verifier = OpmFlowService(arguments.workspace)
    sessions = ResInsightSessionService(store, RipsApplicationFactory(output / "native-logs"))
    views = ResInsightViewService(store, sessions, RipsViewBackend())
    results = ResultsService(
        store, sessions, views, RipsResultBackend(), arguments.workspace / "p12-bundles", verifier
    )
    for label, result in (("baseline", baseline), ("scenario", scenario)):
        bundle = value(results.materialize(result_ref(result)))
        record(
            output / f"{label}-bundle.json",
            {"directory": str(bundle.directory), "result": result.model_dump(mode="json")},
        )
        record(output / f"{label}-dataset.json", source_dataset(store, result))
    source_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=arguments.native_source, text=True
    ).strip()
    assert source_commit.startswith("70399abb9eba31f713f72028ffe94ae0be4db2c4"), (
        "The trial requires the reviewed native build."
    )
    record(
        output / "environment.json",
        {
            "repository_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True
            ).strip(),
            "native_source_commit": source_commit,
            "executable": str(arguments.executable),
            "rips_version": version("rips"),
            "rips_installation": distribution("rips").read_text("direct_url.json"),
            "environment": {
                key: os.environ.get(key)
                for key in ("PYTHONPATH", "QT_PLUGIN_PATH", "DYLD_LIBRARY_PATH")
            },
            "started_at": datetime.now(UTC).isoformat(),
        },
    )
    connection = value(
        sessions.launch(
            LaunchRequest(session_id=arguments.session, executable=arguments.executable)
        )
    )
    record(output / "connection.json", connection)
    try:
        loaded = []
        context = connection.context
        for result in (baseline, scenario):
            job = value(store.get_job(JobRef(session_id=arguments.session, job_id=result.job_id)))
            item = value(results.load(ResultImportRequest(context=context, job=job, result=result)))
            loaded.append(item)
            context = item.case.context
        rebound = value(results.rebind(context, (baseline.result_id, scenario.result_id)))
        for label, item in zip(("baseline", "scenario"), rebound, strict=True):
            native_evidence(
                sessions, item, source_dataset(store, item.result), output / f"{label}-native.json"
            )
        capture_pair(store, sessions, views, results, rebound, output)
        queries = [
            CurveQuery(
                result=result_ref(item), scope="well", keyword="WBHP", well_name=arguments.well
            )
            for item in (baseline, scenario)
        ]
        record(output / "well-comparison.json", value(results.compare_curves(*queries)))
        well_request = SummaryPlotRequest(context=context, query=queries[1], width=1200, height=800)
        record(output / "well-plot-request.json", well_request)
        edited_plot = value(results.show_curve(well_request))
        record(output / "well-plot-edit.json", edited_plot)
        plot = value(edited_plot.observation)
        record(output / "well-plot.json", plot)
        export_artifact(store, plot.image.artifact, output / "well-plot.png")
        state = value(sessions.inspect_project(arguments.session))
        before = plot_inventory(sessions, state)
        record(output / "plots-before-field.json", before)
        prior_parents = {item["address"]: item["parent_window_id"] for item in before["plots"]}
        assert isinstance(prior_parents[plot.plot_address], int)
        assert prior_parents[plot.plot_address] >= 0
        field_request = SummaryPlotRequest(
            context=state.context,
            query=CurveQuery(result=result_ref(scenario), scope="field", keyword="FOPR"),
            width=1000,
            height=700,
        )
        record(output / "field-plot-request.json", field_request)
        field_edit = value(results.show_curve(field_request))
        record(output / "field-plot-edit.json", field_edit)
        field_plot = value(field_edit.observation)
        record(output / "field-plot.json", field_plot)
        export_artifact(store, field_plot.image.artifact, output / "field-plot.png")
        state = value(sessions.inspect_project(arguments.session))
        after = plot_inventory(sessions, state)
        record(output / "plots-after-field.json", after)
        parents = {item["address"]: item["parent_window_id"] for item in after["plots"]}
        assert plot.plot_address != field_plot.plot_address
        assert parents[plot.plot_address] == prior_parents[plot.plot_address]
        assert isinstance(parents[field_plot.plot_address], int)
        assert parents[field_plot.plot_address] >= 0
        assert parents[plot.plot_address] != parents[field_plot.plot_address]
        rebound = value(results.rebind(state.context, (baseline.result_id, scenario.result_id)))
        restored = checkpoint_trial(store, sessions, results, rebound, output)
        for label, item in zip(("baseline", "scenario"), restored, strict=True):
            native_evidence(
                sessions,
                item,
                source_dataset(store, item.result),
                output / f"{label}-restored-native.json",
            )
        record(
            output / "completed.json",
            {
                "completed_at": datetime.now(UTC).isoformat(),
                "automated_checks_passed": True,
                "acceptance_complete": False,
                "visual_review": "pending",
            },
        )
    finally:
        closed = sessions.close(
            CloseRequest(
                session_id=arguments.session,
                connection_id=connection.context.connection_id,
                action=CloseAction.TERMINATE,
            )
        )
        record(output / "close.json", closed)
        value(closed)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("workspace", "output", "executable", "native-source"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--session", type=SessionId, required=True)
    parser.add_argument("--baseline", type=ResultId, required=True)
    parser.add_argument("--scenario", type=ResultId, required=True)
    parser.add_argument("--well", required=True)
    arguments = parser.parse_args()
    for name in ("workspace", "executable", "native_source"):
        setattr(arguments, name, getattr(arguments, name).resolve(strict=True))
    trial(arguments)


if __name__ == "__main__":
    main()
