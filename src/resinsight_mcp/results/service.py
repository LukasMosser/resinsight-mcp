"""Read accepted numerical results and bind verified native cases."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol

from PIL import Image

from resinsight_mcp.contracts.errors import (
    ContractError,
    Error,
    ErrorCode,
    Failure,
    MutationEffect,
    OperationResult,
    Success,
)
from resinsight_mcp.contracts.identifiers import (
    ArtifactId,
    CheckpointId,
    EditId,
    ObservationId,
    ResultId,
    SessionId,
)
from resinsight_mcp.contracts.interfaces import WorkspaceStore
from resinsight_mcp.contracts.jobs import (
    JobRef,
    LoadedResult,
    NumericalAssessment,
    Result,
    ResultImportRequest,
)
from resinsight_mcp.contracts.models import ArtifactRef
from resinsight_mcp.contracts.observations import ImageArtifact, Legend
from resinsight_mcp.contracts.results import ResultDataset, ResultOutputRole
from resinsight_mcp.contracts.sessions import (
    ApplicationContext,
    ObjectKind,
    ObjectRef,
    ProjectState,
)
from resinsight_mcp.contracts.workspace import Artifact, ArtifactKind
from resinsight_mcp.resinsight.sessions._backend import ApplicationAccess, ProjectMutation

from ._bundles import Bundles, ResultBundle
from ._common import fail, operation, value
from .records import (
    CellComparison,
    CellQuery,
    CellValues,
    CurveComparison,
    CurveQuery,
    CurveValues,
    EditedSummaryPlot,
    ResultRef,
    SummaryObservation,
    SummaryPlotEditReceipt,
    SummaryPlotRequest,
)


class Sessions(Protocol):
    def inspect_project(self, session_id: SessionId) -> OperationResult[ProjectState]: ...
    def access_objects(
        self, references: tuple[ObjectRef, ...]
    ) -> AbstractContextManager[ApplicationAccess]: ...
    def mutate_project[T](
        self,
        context: ApplicationContext,
        change: Callable[[ApplicationAccess], T],
        *,
        validate: Callable[[ProjectMutation[T]], None] | None = None,
    ) -> ProjectMutation[T]: ...


class Bindings(Protocol):
    def bind_result(self, loaded: LoadedResult) -> OperationResult[LoadedResult]: ...


class ResultVerifier(Protocol):
    def verify_outputs(self, result: Result, directory: Path) -> OperationResult[ResultDataset]:
        """Verify all five materialized files through the simulator owner's semantic reader."""
        ...


class ResultBackend(Protocol):
    def load(
        self, access: ApplicationAccess, bundle: ResultBundle, dataset: ResultDataset
    ) -> str: ...
    def verify(
        self,
        access: ApplicationAccess,
        case_address: str,
        bundle: ResultBundle,
        dataset: ResultDataset,
    ) -> None: ...
    def show_curve(
        self,
        access: ApplicationAccess,
        bundle: ResultBundle,
        dataset: ResultDataset,
        curve: CurveValues,
        folder: Path,
        width: int,
        height: int,
    ) -> str: ...


class ResultsService:
    def __init__(
        self,
        workspaces: WorkspaceStore,
        sessions: Sessions,
        views: Bindings,
        backend: ResultBackend,
        bundle_root: Path,
        verifier: ResultVerifier,
    ) -> None:
        self._workspaces = workspaces
        self._sessions = sessions
        self._views = views
        self._backend = backend
        self._bundles = Bundles(workspaces, bundle_root)
        self._verifier = verifier

    def _read(self, reference: ResultRef) -> tuple[Result, ResultDataset]:
        result = value(self._workspaces.get_result(reference.session_id, reference.result_id))
        if result.assessment != NumericalAssessment.ACCEPTED or result.manifest is None:
            fail(
                ErrorCode.INVALID_MODEL, "Queries and loading require an accepted result manifest."
            )
        with self._workspaces.open_artifact(result.manifest.numerical_data) as stream:
            dataset = ResultDataset.model_validate_json(stream.read())
        if (
            dataset.model != result.model
            or dataset.job_id != result.job_id
            or dataset.active_cells != result.manifest.active_cells
            or dataset.report_series != result.report_series
        ):
            fail(ErrorCode.INVALID_MODEL, "The numerical dataset differs from its stored result.")
        revision = value(self._workspaces.get_revision(result.model))
        if dataset.geometry.coordinates != revision.coordinates:
            fail(
                ErrorCode.INVALID_MODEL,
                "The result coordinates differ from the stored model revision.",
            )
        return result, dataset

    @operation
    def materialize(self, reference: ResultRef) -> ResultBundle:
        result, dataset = self._read(reference)
        return self._materialize(result, dataset)

    def _materialize(self, result: Result, dataset: ResultDataset) -> ResultBundle:
        bundle = self._bundles.materialize(result)
        verified = value(self._verifier.verify_outputs(result, bundle.directory))
        if verified != dataset:
            fail(
                ErrorCode.INVALID_MODEL,
                "The materialized outputs differ from the accepted dataset.",
            )
        return bundle

    @operation
    def cell_property(self, query: CellQuery) -> CellValues:
        result, dataset = self._read(query.result)
        if query.report_time not in dataset.report_series.reports:
            fail(ErrorCode.INVALID_MODEL, "The requested report does not belong to this result.")
        matches = [item for item in dataset.cell_properties if item.name == query.property]
        if len(matches) != 1:
            fail(ErrorCode.NOT_FOUND, "The requested cell property is unavailable.")
        item = matches[0]
        index = dataset.report_series.reports.index(query.report_time)
        return CellValues(
            result=result,
            active_cells=dataset.active_cells,
            geometry=dataset.geometry,
            property=item.name,
            unit=item.unit,
            report_time=query.report_time,
            values=item.values[index],
        )

    @operation
    def curve(self, query: CurveQuery) -> CurveValues:
        result, dataset = self._read(query.result)
        matches = [
            item
            for item in dataset.curves
            if (item.scope, item.keyword, item.well_name)
            == (query.scope, query.keyword, query.well_name)
        ]
        if len(matches) != 1:
            fail(ErrorCode.NOT_FOUND, "The requested summary curve is unavailable.")
        item = matches[0]
        return CurveValues(
            result=result,
            scope=item.scope,
            keyword=item.keyword,
            well_name=item.well_name,
            unit=item.unit,
            reports=dataset.report_series.reports,
            values=item.values,
        )

    @operation
    def compare_cells(self, baseline: CellQuery, scenario: CellQuery) -> CellComparison:
        left, right = value(self.cell_property(baseline)), value(self.cell_property(scenario))
        if (
            left.result.model.session_id != right.result.model.session_id
            or left.property != right.property
            or left.unit != right.unit
            or left.active_cells.dimensions != right.active_cells.dimensions
            or left.active_cells.cells != right.active_cells.cells
            or left.geometry != right.geometry
            or (left.report_time.calendar_date, left.report_time.elapsed_days)
            != (right.report_time.calendar_date, right.report_time.elapsed_days)
        ):
            fail(
                ErrorCode.INVALID_MODEL,
                "Cell comparison requires matching grids, properties, units, and times.",
            )
        combined = left.values + right.values
        if not combined:
            fail(ErrorCode.INVALID_MODEL, "Cell comparison requires active cell values.")
        low, high = min(combined), max(combined)
        if low == high:
            high = low + max(abs(low) * 0.01, 1.0)
        return CellComparison(
            baseline=left,
            scenario=right,
            differences=tuple(b - a for a, b in zip(left.values, right.values, strict=True)),
            legend=Legend(minimum=low, maximum=high),
        )

    @operation
    def compare_curves(self, baseline: CurveQuery, scenario: CurveQuery) -> CurveComparison:
        left, right = value(self.curve(baseline)), value(self.curve(scenario))
        if left.result.model.session_id != right.result.model.session_id:
            fail(ErrorCode.INVALID_MODEL, "Compared curves must belong to one session.")
        if (left.scope, left.keyword, left.well_name, left.unit) != (
            right.scope,
            right.keyword,
            right.well_name,
            right.unit,
        ) or tuple((r.calendar_date, r.elapsed_days) for r in left.reports) != tuple(
            (r.calendar_date, r.elapsed_days) for r in right.reports
        ):
            fail(
                ErrorCode.INVALID_MODEL,
                "Curve comparison requires matching quantities, units, and report times.",
            )
        return CurveComparison(
            baseline=left,
            scenario=right,
            differences=tuple(b - a for a, b in zip(left.values, right.values, strict=True)),
        )

    @operation
    def load(self, request: ResultImportRequest) -> LoadedResult:
        result, dataset = self._read(
            ResultRef(session_id=request.context.session_id, result_id=request.result.result_id)
        )
        if result != request.result:
            fail(ErrorCode.INVALID_MODEL, "The load request differs from the stored result.")
        stored_job = value(
            self._workspaces.get_job(
                JobRef(session_id=result.model.session_id, job_id=result.job_id)
            )
        )
        if stored_job != request.job:
            fail(ErrorCode.INVALID_MODEL, "The load request differs from the stored job.")
        bundle = self._materialize(result, dataset)
        mutation = self._sessions.mutate_project(
            request.context,
            lambda access: self._backend.load(access, bundle, dataset),
            validate=lambda current: self._backend.verify(
                current.access, current.value, bundle, dataset
            ),
        )
        case = self._case(mutation.access, mutation.value)
        return value(self._views.bind_result(LoadedResult(case=case, result=result)))

    @staticmethod
    def _case(access: ApplicationAccess, address: str) -> ObjectRef:
        matches = [
            item.ref
            for item, native in zip(access.project.objects, access.objects, strict=True)
            if native.kind == ObjectKind.CASE and native.address == address
        ]
        if len(matches) != 1:
            fail(ErrorCode.STALE_OBJECT, "The loaded native case has no unique current reference.")
        return matches[0]

    @operation
    def restore(
        self, context: ApplicationContext, checkpoint_id: CheckpointId
    ) -> tuple[LoadedResult, ...]:
        checkpoint = value(self._workspaces.get_checkpoint(context.session_id, checkpoint_id))
        return self._rebind(context, checkpoint.result_ids)

    @operation
    def rebind(
        self, context: ApplicationContext, result_ids: tuple[ResultId, ...]
    ) -> tuple[LoadedResult, ...]:
        """Verify current loaded results after a project mutation without requiring a checkpoint."""
        return self._rebind(context, result_ids)

    def _rebind(
        self, context: ApplicationContext, result_ids: tuple[ResultId, ...]
    ) -> tuple[LoadedResult, ...]:
        if not result_ids or len(set(result_ids)) != len(result_ids):
            fail(
                ErrorCode.INVALID_MODEL, "Rebinding requires distinct explicit result identifiers."
            )
        project = value(self._sessions.inspect_project(context.session_id))
        if project.context != context:
            fail(ErrorCode.STALE_OBJECT, "The project context changed before result restoration.")
        references = tuple(item.ref for item in project.objects if item.ref.kind == ObjectKind.CASE)
        if not references:
            fail(
                ErrorCode.NOT_FOUND,
                "Result rebinding requires current native cases.",
            )
        loaded = []
        for result_id in result_ids:
            result, dataset = self._read(
                ResultRef(session_id=context.session_id, result_id=result_id)
            )
            bundle = self._materialize(result, dataset)
            with self._sessions.access_objects(references) as access:
                matches = [
                    (ref, native)
                    for ref, native in zip(references, access.objects, strict=True)
                    if dict(native.attributes).get("file_path") == str(bundle.egrid)
                ]
                if len(matches) != 1:
                    fail(ErrorCode.STALE_OBJECT, "The saved result has no unique native case path.")
                case, native = matches[0]
                self._backend.verify(access, native.address, bundle, dataset)
            loaded.append(LoadedResult(case=case, result=result))
        return tuple(value(self._views.bind_result(item)) for item in loaded)

    @operation
    def show_curve(self, request: SummaryPlotRequest) -> EditedSummaryPlot:
        if request.context.session_id != request.query.result.session_id:
            fail(ErrorCode.INVALID_MODEL, "The summary plot and result must share one session.")
        curve = value(self.curve(request.query))
        result, dataset = self._read(request.query.result)
        bundle = self._materialize(result, dataset)
        observation_id = ObservationId.new()
        edit: SummaryPlotEditReceipt | None = None
        native_started = False
        try:
            with TemporaryDirectory(prefix="resinsight-summary-") as temporary:
                folder = Path(temporary)
                native_started = True
                mutation = self._sessions.mutate_project(
                    request.context,
                    lambda access: self._backend.show_curve(
                        access, bundle, dataset, curve, folder, request.width, request.height
                    ),
                )
                edit = SummaryPlotEditReceipt(
                    edit_id=EditId.new(),
                    context=mutation.access.project.context,
                    curve=curve,
                    plot_address=mutation.value,
                )
                observation = self._save_summary(request, edit, observation_id, folder)
            return EditedSummaryPlot(
                edit=edit, observation=OperationResult(outcome=Success(value=observation))
            )
        except (ContractError, OSError, ValueError, Image.DecompressionBombError) as error:
            if edit is not None:
                detail = error.error.message if isinstance(error, ContractError) else str(error)
                return EditedSummaryPlot(
                    edit=edit,
                    observation=OperationResult(
                        outcome=Failure(
                            error=Error(
                                code=ErrorCode.RENDER_FAILED,
                                message=(
                                    "The summary plot was created, but image handling failed: "
                                    f"{detail}"
                                ),
                                effect=MutationEffect.UNKNOWN,
                            )
                        )
                    ),
                )
            if native_started and not isinstance(error, ContractError):
                raise ContractError(
                    Error(
                        code=ErrorCode.EXECUTION_FAILED,
                        message="The summary plot outcome could not be confirmed.",
                        effect=MutationEffect.UNKNOWN,
                    )
                ) from error
            raise

    def _save_summary(
        self,
        request: SummaryPlotRequest,
        edit: SummaryPlotEditReceipt,
        observation_id: ObservationId,
        folder: Path,
    ) -> SummaryObservation:
        curve = edit.curve
        images = tuple(folder.glob("*.png"))
        if len(images) != 1:
            fail(ErrorCode.RENDER_FAILED, "The summary export requires exactly one new PNG image.")
        with Image.open(images[0]) as image:
            image.load()
            if image.format != "PNG" or image.size != (request.width, request.height):
                fail(
                    ErrorCode.RENDER_FAILED, "The summary image dimensions differ from the request."
                )
        session_id = curve.result.model.session_id
        artifact = Artifact(
            ref=ArtifactRef(session_id=session_id, artifact_id=ArtifactId.new()),
            relative_path=f"summary-observations/{observation_id}.png",
            kind=ArtifactKind.IMAGE,
        )
        with images[0].open("rb") as source:
            value(self._workspaces.write_artifact(artifact, source))
        provenance = Artifact(
            ref=ArtifactRef(session_id=session_id, artifact_id=ArtifactId.new()),
            relative_path=f"summary-observations/{observation_id}.json",
            kind=ArtifactKind.METADATA,
        )
        assert curve.result.manifest is not None
        smspec = next(
            item.artifact
            for item in curve.result.manifest.outputs
            if item.role == ResultOutputRole.SMSPEC
        )
        observation = SummaryObservation(
            observation_id=observation_id,
            context=edit.context,
            curve=curve,
            plot_address=edit.plot_address,
            source=smspec,
            image=ImageArtifact(artifact=artifact.ref, width=request.width, height=request.height),
            captured_at=datetime.now(UTC),
            provenance=provenance.ref,
        )
        value(
            self._workspaces.write_artifact(
                provenance, BytesIO(observation.model_dump_json().encode("utf-8"))
            )
        )
        return observation
