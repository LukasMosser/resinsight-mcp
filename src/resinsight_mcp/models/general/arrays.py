"""Store immutable numeric arrays and read only the requested chunks."""

import io
from collections.abc import Callable, Iterator
from functools import wraps
from typing import Literal, NoReturn

import numpy as np
from numpy.typing import NDArray
from pydantic import FiniteFloat, NonNegativeInt, PositiveFloat, PositiveInt

from resinsight_mcp.contracts._base import Record, Text
from resinsight_mcp.contracts.errors import (
    ContractError,
    Error,
    ErrorCode,
    Failure,
    OperationResult,
    Success,
)
from resinsight_mcp.contracts.identifiers import ArtifactId, SessionId
from resinsight_mcp.contracts.interfaces import WorkspaceStore
from resinsight_mcp.contracts.models import ArtifactRef
from resinsight_mcp.contracts.workspace import Artifact, ArtifactKind

type NumericArray = NDArray[np.float64] | NDArray[np.int64]


def fail(message: str, code: ErrorCode = ErrorCode.INVALID_MODEL) -> NoReturn:
    raise ContractError(Error(code=code, message=message))


def value[T](result: OperationResult[T]) -> T:
    if isinstance(result.outcome, Failure):
        raise ContractError(result.outcome.error)
    return result.outcome.value


def operation[**P, T](method: Callable[P, T]) -> Callable[P, OperationResult[T]]:
    @wraps(method)
    def run(*args: P.args, **kwargs: P.kwargs) -> OperationResult[T]:
        try:
            return OperationResult(outcome=Success(value=method(*args, **kwargs)))
        except ContractError as error:
            return OperationResult(outcome=Failure(error=error.error))
        except (OSError, ValueError, MemoryError) as error:
            return OperationResult(
                outcome=Failure(error=Error(code=ErrorCode.EXECUTION_FAILED, message=str(error)))
            )

    return run


class AuthoringPolicy(Record):
    """Operator budgets limit work, never the model's cell or well count."""

    working_memory_mib: PositiveInt = 512
    request_values: PositiveInt = 65_536
    response_values: PositiveInt = 4_096
    request_records: PositiveInt = 256
    response_records: PositiveInt = 128
    native_rpc_timeout_seconds: PositiveFloat = 30
    native_launch_timeout_seconds: PositiveFloat = 120
    parser_memory_mib: PositiveInt = 1024
    parser_timeout_seconds: PositiveFloat = 120
    compilation_disk_mib: PositiveInt = 1024

    def require_memory(self, estimated_mib: float) -> None:
        if estimated_mib > self.working_memory_mib:
            fail(
                f"Estimated working memory is {estimated_mib:.2f} MiB. "
                f"The configured budget is {self.working_memory_mib} MiB."
            )


class ArrayInfo(Record):
    artifact: ArtifactRef
    count: PositiveInt
    dtype: Literal["float64", "int64"]
    unit: Text
    minimum: FiniteFloat
    maximum: FiniteFloat


class ArrayChunk(Record):
    artifact: ArtifactRef
    count: PositiveInt


class ArrayDescriptor(ArrayInfo):
    version: Literal["numeric-array-v1"] = "numeric-array-v1"
    chunks: tuple[ArrayChunk, ...]

    def info(self) -> ArrayInfo:
        return ArrayInfo.model_validate(self.model_dump(include=ArrayInfo.model_fields.keys()))


class ArrayWriteRequest(Record):
    session_id: SessionId
    dtype: Literal["float64", "int64"]
    unit: Text
    values: tuple[FiniteFloat, ...]


class ArrayJoinRequest(Record):
    session_id: SessionId
    parts: tuple[ArtifactRef, ...]


class ArrayRangeRequest(Record):
    array: ArtifactRef
    offset: NonNegativeInt
    count: PositiveInt


class ArrayRange(Record):
    array: ArrayInfo
    offset: NonNegativeInt
    values: tuple[FiniteFloat, ...]
    next_offset: NonNegativeInt | None


class ArrayService:
    def __init__(self, store: WorkspaceStore, policy: AuthoringPolicy) -> None:
        self.store = store
        self.policy = policy

    def publish(
        self, ref: ArtifactRef, record: Record, kind: ArtifactKind = ArtifactKind.INPUT
    ) -> None:
        value(
            self.store.write_artifact(
                Artifact(
                    ref=ref,
                    relative_path=f"general/{ref.artifact_id}/record.json",
                    kind=kind,
                ),
                io.BytesIO(record.model_dump_json().encode()),
            )
        )

    def write(self, session: SessionId, array: NumericArray, unit: str) -> ArrayInfo:
        value(self.store.get_session(session))
        if (
            array.ndim != 1
            or not array.size
            or array.dtype not in (np.dtype("float64"), np.dtype("int64"))
        ):
            fail("Arrays require nonempty one-dimensional float64 or int64 values.")
        self.policy.require_memory((array.nbytes + self.policy.request_values * 16) / 1024**2)
        if not np.isfinite(array).all():
            fail("Array values must be finite.")
        chunks = []
        for offset in range(0, array.size, self.policy.request_values):
            part = array[offset : offset + self.policy.request_values]
            ref = ArtifactRef(session_id=session, artifact_id=ArtifactId.new())
            stream = io.BytesIO()
            np.save(stream, part, allow_pickle=False)
            stream.seek(0)
            value(
                self.store.write_artifact(
                    Artifact(
                        ref=ref,
                        relative_path=f"general/{ref.artifact_id}/values.npy",
                        kind=ArtifactKind.INPUT,
                    ),
                    stream,
                )
            )
            chunks.append(ArrayChunk(artifact=ref, count=int(part.size)))
        descriptor = ArrayDescriptor(
            artifact=ArtifactRef(session_id=session, artifact_id=ArtifactId.new()),
            count=int(array.size),
            dtype="float64" if array.dtype == np.float64 else "int64",
            unit=unit,
            minimum=float(array.min()),
            maximum=float(array.max()),
            chunks=tuple(chunks),
        )
        self.publish(descriptor.artifact, descriptor)
        return descriptor.info()

    def descriptor(self, ref: ArtifactRef) -> ArrayDescriptor:
        with self.store.open_artifact(ref) as stream:
            descriptor = ArrayDescriptor.model_validate_json(stream.read())
        if descriptor.artifact != ref or any(
            c.artifact.session_id != ref.session_id for c in descriptor.chunks
        ):
            fail("The array descriptor has a different ownership identity.")
        if sum(c.count for c in descriptor.chunks) != descriptor.count:
            fail("The array chunk counts differ from the declared size.")
        return descriptor

    def chunks(
        self, ref: ArtifactRef, offset: int = 0, count: int | None = None
    ) -> Iterator[NumericArray]:
        descriptor = self.descriptor(ref)
        end = descriptor.count if count is None else offset + count
        start = 0
        for chunk in descriptor.chunks:
            stop = start + chunk.count
            if start < end and stop > offset:
                self.policy.require_memory(chunk.count * 16 / 1024**2)
                with self.store.open_artifact(chunk.artifact) as stream:
                    array = np.load(stream, allow_pickle=False)
                if (
                    array.shape != (chunk.count,)
                    or str(array.dtype) != descriptor.dtype
                    or not np.isfinite(array).all()
                ):
                    fail("The stored chunk differs from its numeric declaration.")
                yield array[max(0, offset - start) : min(chunk.count, end - start)]
            start = stop
            if start >= end:
                break

    def read(self, ref: ArtifactRef) -> NumericArray:
        descriptor = self.descriptor(ref)
        self.policy.require_memory((descriptor.count + self.policy.request_values) * 16 / 1024**2)
        array = np.empty(descriptor.count, dtype=descriptor.dtype)
        offset = 0
        for part in self.chunks(ref):
            array[offset : offset + part.size] = part
            offset += part.size
        return array

    @operation
    def upload(self, request: ArrayWriteRequest) -> ArrayInfo:
        if not 0 < len(request.values) <= self.policy.request_values:
            fail("The upload exceeds the configured request size. Upload parts and join them.")
        array = np.asarray(request.values, dtype=np.float64)
        if request.dtype == "int64":
            if np.any(array != np.floor(array)) or np.any(np.abs(array) > 2**53 - 1):
                fail("JSON integer values must be exactly representable within 53 bits.")
            array = array.astype(np.int64)
        return self.write(request.session_id, array, request.unit)

    @operation
    def join(self, request: ArrayJoinRequest) -> ArrayInfo:
        if not 0 < len(request.parts) <= self.policy.request_values:
            fail("The part list exceeds the configured request size.")
        if any(ref.session_id != request.session_id for ref in request.parts):
            fail("Every array part must belong to this session.")
        parts = [self.descriptor(ref) for ref in request.parts]
        first = parts[0]
        if any((p.dtype, p.unit) != (first.dtype, first.unit) for p in parts):
            fail("Joined arrays require the same numeric type and unit.")
        descriptor = ArrayDescriptor(
            artifact=ArtifactRef(session_id=request.session_id, artifact_id=ArtifactId.new()),
            count=sum(p.count for p in parts),
            dtype=first.dtype,
            unit=first.unit,
            minimum=min(p.minimum for p in parts),
            maximum=max(p.maximum for p in parts),
            chunks=tuple(c for p in parts for c in p.chunks),
        )
        self.publish(descriptor.artifact, descriptor)
        return descriptor.info()

    @operation
    def inspect(self, ref: ArtifactRef) -> ArrayInfo:
        return self.descriptor(ref).info()

    @operation
    def query(self, request: ArrayRangeRequest) -> ArrayRange:
        if request.count > self.policy.response_values:
            fail("The requested range exceeds the configured response size.")
        descriptor = self.descriptor(request.array)
        end = request.offset + request.count
        if end > descriptor.count:
            fail("The requested range falls outside the stored array.")
        return ArrayRange(
            array=descriptor.info(),
            offset=request.offset,
            values=tuple(
                float(item)
                for part in self.chunks(request.array, request.offset, request.count)
                for item in part
            ),
            next_offset=end if end < descriptor.count else None,
        )
