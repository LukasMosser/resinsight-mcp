"""Stage fixed models, submit durable Flow jobs, and publish verified outputs."""

import io
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from pydantic import BaseModel

from resinsight_mcp.contracts.errors import (
    ContractError,
    Error,
    ErrorCode,
    Failure,
    MutationEffect,
    OperationResult,
    Success,
)
from resinsight_mcp.contracts.identifiers import ArtifactId, GridId, ResultId
from resinsight_mcp.contracts.jobs import (
    DockerExecution,
    DockerMount,
    Job,
    JobRef,
    JobRequest,
    JobState,
    NumericalAssessment,
    Result,
)
from resinsight_mcp.contracts.models import ArtifactRef, Backend
from resinsight_mcp.contracts.results import (
    ResultDataset,
    ResultManifest,
    ResultOutput,
    ResultOutputRole,
)
from resinsight_mcp.contracts.workspace import Artifact, ArtifactKind
from resinsight_mcp.jobs import DurableJobController, JobCommand
from resinsight_mcp.models.imports import OpmImportService
from resinsight_mcp.workspaces import SqliteWorkspaceStore

from .configuration import FlowConfiguration
from .records import FlowAssessment, FlowRunRecord


def _value[T](result: OperationResult[T]) -> T:
    if isinstance(result.outcome, Failure):
        raise ContractError(result.outcome.error)
    return result.outcome.value


def _invalid(message: str) -> ContractError:
    return ContractError(Error(code=ErrorCode.INVALID_MODEL, message=message))


class OpmFlowService:
    """Run the bounded FIELD profile in the pinned local Docker image."""

    def __init__(self, workspace: Path, configuration: FlowConfiguration | None = None) -> None:
        self.workspace = workspace.resolve(strict=True)
        if "," in str(self.workspace):
            raise ContractError(
                Error(
                    code=ErrorCode.INVALID_PATH, message="Docker mount paths cannot contain commas."
                )
            )
        self.configuration = configuration or FlowConfiguration()
        self.store = SqliteWorkspaceStore.open(self.workspace)
        self.imports = OpmImportService(self.store)
        self.jobs = DurableJobController(self.workspace, self._resolve)
        self.runtime = self.workspace / "opm-runs"
        self.runtime.mkdir(mode=0o700, exist_ok=True)

    def submit(self, request: JobRequest) -> OperationResult[Job]:
        return self.jobs.submit(request)

    def poll(self, job: JobRef) -> OperationResult[Job]:
        return self.jobs.poll(job)

    def request_cancel(self, job: JobRef) -> OperationResult[Job]:
        return self.jobs.request_cancel(job)

    def _resolve(self, request: JobRequest) -> JobCommand:
        if request.prepared.backend != Backend.OPM_FLOW:
            raise _invalid("The Flow service requires the OPM backend.")
        limits = request.limits
        if limits.cpu_count > 2 or limits.memory_mib > 2048 or limits.wall_time_seconds > 60:
            raise _invalid("Flow runs allow at most two CPUs, 2048 MiB, and 60 wall seconds.")
        client, server = self.configuration.runtime_versions()
        model = request.prepared.revision.model
        run_id = uuid4().hex
        directory = self.runtime / run_id
        directory.mkdir(mode=0o700)
        with self.imports.materialize(model) as materialized:
            shutil.copytree(materialized.directory, directory / "inputs")
            entrypoint = materialized.entrypoint.relative_to(materialized.directory).as_posix()
            inspection = materialized.inspection
        (directory / "outputs").mkdir(mode=0o700)
        ref = ArtifactRef(session_id=model.session_id, artifact_id=ArtifactId.new())
        record = FlowRunRecord(
            model=model,
            coordinates=request.prepared.revision.coordinates,
            result_id=ResultId.new(),
            grid_id=GridId.new(),
            directory=directory,
            entrypoint=entrypoint,
            inspection=inspection,
            outputs=tuple(
                ResultOutput(
                    role=role,
                    artifact=ArtifactRef(session_id=model.session_id, artifact_id=ArtifactId.new()),
                )
                for role in ResultOutputRole
            ),
            numerical_data=ArtifactRef(session_id=model.session_id, artifact_id=ArtifactId.new()),
            assessment_evidence=ArtifactRef(
                session_id=model.session_id, artifact_id=ArtifactId.new()
            ),
            expected_program_version=self.configuration.program_version,
        )
        execution = DockerExecution(
            image_digest=self.configuration.image,
            platform=self.configuration.platform,
            container_name=f"resinsight-opm-{run_id}",
            ownership_token=uuid4().hex,
            program_version=self.configuration.program_version,
            docker_client_version=client,
            docker_server_version=server,
            command=("flow", f"/input/{entrypoint}", "--output-dir=/output"),
            mounts=(
                DockerMount(source=str(directory / "inputs"), target="/input", read_only=True),
                DockerMount(source=str(directory / "outputs"), target="/output", read_only=False),
            ),
            working_directory="/output",
        )
        self._write_json(ref, f"runs/{run_id}/run.json", record)
        return JobCommand(
            argv=(str(self.configuration.docker),),
            working_directory=directory,
            execution=execution,
            run_metadata=ref,
        )

    def _write_json(self, ref: ArtifactRef, name: str, record: BaseModel) -> None:
        self._publish(
            Artifact(ref=ref, relative_path=name, kind=ArtifactKind.METADATA),
            io.BytesIO(record.model_dump_json().encode()),
        )

    def _publish(self, artifact: Artifact, source: BinaryIO) -> None:
        existing = self.store.get_artifact(artifact.ref)
        if isinstance(existing.outcome, Success):
            if existing.outcome.value != artifact:
                raise _invalid("A reserved output artifact has different metadata.")
            return
        if existing.outcome.error.code != ErrorCode.NOT_FOUND:
            raise ContractError(existing.outcome.error)
        _value(self.store.write_artifact(artifact, source))

    def _run_record(self, job: Job) -> FlowRunRecord:
        submission = job.submission
        if (
            job.backend != Backend.OPM_FLOW
            or submission is None
            or submission.execution is None
            or submission.run_metadata is None
        ):
            raise _invalid("This job has no recorded Flow execution.")
        with self.store.open_artifact(submission.run_metadata) as source:
            record = FlowRunRecord.model_validate_json(source.read())
        if (
            record.model != job.model
            or record.directory.parent != self.runtime
            or record.directory.resolve() != record.directory
            or str(record.directory) != submission.working_directory
            or submission.execution.image_digest != self.configuration.image
            or submission.execution.program_version != self.configuration.program_version
            or submission.execution.platform != self.configuration.platform
            or submission.execution.program_version != record.expected_program_version
        ):
            raise _invalid("The run metadata differs from the recorded job identity.")
        return record

    def _read(self, job: Job, run: FlowRunRecord) -> tuple[ResultDataset, FlowAssessment]:
        for output in run.outputs:
            path = run.directory / "outputs" / f"{Path(run.entrypoint).stem}.{output.role.value}"
            if not path.is_file() or path.is_symlink():
                raise _invalid(f"Expected output is missing or linked: {output.role.value}.")
        log = []
        for ref in job.logs:
            with self.store.open_artifact(ref) as source:
                log.append(source.read().decode("utf-8"))
        (run.directory / "reader-run.json").write_text(run.model_dump_json())
        (run.directory / "reader-flow.log").write_text("\n".join(log))
        output = run.directory / "reader-result.json"
        completed = subprocess.run(
            (
                sys.executable,
                "-I",
                "-m",
                "resinsight_mcp.simulators.opm._reader",
                str(run.directory / "reader-run.json"),
                str(job.job_id),
                str(run.directory / "reader-flow.log"),
                str(output),
            ),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if completed.returncode != 0:
            raise _invalid(f"Flow output validation failed: {completed.stderr.strip()}")
        record = json.loads(output.read_text())
        return (
            ResultDataset.model_validate_json(json.dumps(record["dataset"])),
            FlowAssessment.model_validate(record["assessment"]),
        )

    def _read_exact_outputs(
        self, job: Job, run: FlowRunRecord, directory: Path | None
    ) -> tuple[ResultDataset, FlowAssessment]:
        with tempfile.TemporaryDirectory(prefix="opm-verify-", dir=self.runtime) as temporary:
            root = Path(temporary)
            with self.imports.materialize(run.model) as materialized:
                if (
                    materialized.inspection != run.inspection
                    or materialized.revision.coordinates != run.coordinates
                    or materialized.entrypoint.relative_to(materialized.directory).as_posix()
                    != run.entrypoint
                ):
                    raise _invalid("The saved run identity differs from the immutable model.")
                shutil.copytree(materialized.directory, root / "inputs")
            outputs = root / "outputs"
            outputs.mkdir()
            for item in run.outputs:
                name = f"{Path(run.entrypoint).stem}.{item.role.value}"
                if directory is None:
                    with self.store.open_artifact(item.artifact) as source:
                        with (outputs / name).open("wb") as target:
                            shutil.copyfileobj(source, target)
                else:
                    source_path = directory / name
                    if not source_path.is_file() or source_path.is_symlink():
                        raise _invalid(f"Expected output is missing or linked: {item.role.value}.")
                    shutil.copyfile(source_path, outputs / name)
            return self._read(job, run.model_copy(update={"directory": root}))

    def _stored_dataset(self, run: FlowRunRecord) -> tuple[ResultDataset, FlowAssessment]:
        with self.store.open_artifact(run.numerical_data) as source:
            dataset = ResultDataset.model_validate_json(source.read())
        with self.store.open_artifact(run.assessment_evidence) as source:
            assessment = FlowAssessment.model_validate_json(source.read())
        return dataset, assessment

    def verify_outputs(self, result: Result, directory: Path) -> OperationResult[ResultDataset]:
        """Compare exact output semantics with the immutable collected result."""
        try:
            stored = _value(self.store.get_result(result.model.session_id, result.result_id))
            if stored != result:
                raise _invalid("The supplied result differs from its immutable stored record.")
            job = _value(
                self.store.get_job(JobRef(session_id=result.model.session_id, job_id=result.job_id))
            )
            run = self._run_record(job)
            if run.result_id != result.result_id:
                raise _invalid("The result differs from its recorded Flow run.")
            actual = self._read_exact_outputs(job, run, directory)
            if result != self._result(job, run, actual[0]):
                raise _invalid(
                    "The result identity or manifest differs from its recorded Flow run."
                )
            if actual != self._stored_dataset(run):
                raise _invalid("Output semantics differ from the immutable collected result.")
            return OperationResult(outcome=Success(value=actual[0]))
        except ContractError as error:
            return OperationResult(outcome=Failure(error=error.error))
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            return OperationResult(
                outcome=Failure(
                    error=Error(
                        code=ErrorCode.INVALID_MODEL, message=f"Output verification failed: {error}"
                    )
                )
            )

    @staticmethod
    def _result(current: Job, run: FlowRunRecord, dataset: ResultDataset) -> Result:
        return Result(
            result_id=run.result_id,
            job_id=current.job_id,
            model=current.model,
            grid_id=run.grid_id,
            report_series=dataset.report_series,
            assessment=NumericalAssessment.ACCEPTED,
            manifest=ResultManifest(
                outputs=run.outputs,
                active_cells=dataset.active_cells,
                restart_report_steps=tuple(
                    report.index for report in dataset.report_series.reports
                ),
                numerical_data=run.numerical_data,
                assessment_evidence=run.assessment_evidence,
            ),
        )

    def collect(self, job: JobRef) -> OperationResult[Result]:
        """Publish validated output identity without claiming reference agreement."""
        publishing = False
        run: FlowRunRecord | None = None
        try:
            current = _value(self.jobs.poll(job))
            if current.state != JobState.SUCCEEDED:
                raise _invalid("Output collection requires a confirmed successful job.")
            run = self._run_record(current)
            existing = self.store.get_result(job.session_id, run.result_id)
            if isinstance(existing.outcome, Success):
                stored_data, _ = self._stored_dataset(run)
                if existing.outcome.value != self._result(current, run, stored_data):
                    raise _invalid("The stored result identity differs from its recorded Flow run.")
                return existing
            if existing.outcome.error.code != ErrorCode.NOT_FOUND:
                raise ContractError(existing.outcome.error)
            dataset, assessment = self._read_exact_outputs(current, run, run.directory / "outputs")
            publishing = True
            self._publish_result_outputs(run, dataset, assessment)
            published = self._read_exact_outputs(current, run, None)
            if published != (dataset, assessment) or published != self._stored_dataset(run):
                raise _invalid("Published output semantics differ from the collected candidate.")
            result = self._result(current, run, dataset)
            return OperationResult(outcome=Success(value=_value(self.store.save_result(result))))
        except ContractError as error:
            detail = error.error
            if publishing and run is not None:
                detail = detail.model_copy(
                    update={
                        "effect": MutationEffect.UNKNOWN,
                        "message": f"Collection for {run.result_id} is uncertain: {detail.message}",
                    }
                )
            return OperationResult(outcome=Failure(error=detail))
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            return OperationResult(
                outcome=Failure(
                    error=Error(
                        code=ErrorCode.EXECUTION_FAILED,
                        message=f"Result collection failed: {error}",
                        effect=MutationEffect.UNKNOWN if publishing else MutationEffect.NOT_APPLIED,
                    )
                )
            )

    def _publish_result_outputs(
        self, run: FlowRunRecord, dataset: ResultDataset, assessment: FlowAssessment
    ) -> None:
        basename = Path(run.entrypoint).stem
        for output in run.outputs:
            name = f"{basename}.{output.role.value}"
            artifact = Artifact(
                ref=output.artifact,
                relative_path=f"results/{run.result_id}/{name}",
                kind=ArtifactKind.OUTPUT,
            )
            with (run.directory / "outputs" / name).open("rb") as source:
                self._publish(artifact, source)
        self._write_json(run.numerical_data, f"results/{run.result_id}/data.json", dataset)
        self._write_json(
            run.assessment_evidence, f"results/{run.result_id}/assessment.json", assessment
        )
