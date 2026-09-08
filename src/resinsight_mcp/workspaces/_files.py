"""Directory-relative storage for immutable artifact files."""

import errno
import os
import shutil
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

from pydantic import ValidationError

from resinsight_mcp.contracts.errors import ContractError, Error, ErrorCode, MutationEffect
from resinsight_mcp.contracts.identifiers import ArtifactId, SessionId
from resinsight_mcp.contracts.models import ArtifactRef

_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
_DATABASE_NAMES = (
    "workspace.sqlite3",
    "workspace.sqlite3-journal",
    "workspace.sqlite3-wal",
    "workspace.sqlite3-shm",
)


def _failure(code: ErrorCode, message: str) -> ContractError:
    return ContractError(Error(code=code, message=message))


@contextmanager
def _file_errors() -> Iterator[None]:
    """Translate operating-system failures without exposing internal paths."""
    try:
        yield
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            code = ErrorCode.INVALID_PATH
        elif exc.errno == errno.ENOENT:
            code = ErrorCode.NOT_FOUND
        elif exc.errno == errno.EEXIST:
            code = ErrorCode.CONFLICT
        else:
            code = ErrorCode.STORAGE_FAILED
        raise _failure(code, "The workspace file operation failed.") from exc


def _regular(info: os.stat_result, *, allow_unlinked: bool = False) -> None:
    valid_links = (0, 1) if allow_unlinked else (1,)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink not in valid_links:
        raise _failure(
            ErrorCode.INVALID_PATH, "Workspace files must be regular files with one link."
        )


@contextmanager
def _directory(name: str | Path, *, parent: int | None = None) -> Iterator[int]:
    with _file_errors():
        descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent)
    try:
        yield descriptor
    finally:
        os.close(descriptor)


def _make_directory(name: str, parent: int) -> None:
    try:
        os.mkdir(name, mode=0o700, dir_fd=parent)
    except FileExistsError:
        return
    os.fsync(parent)


def _entry_info(name: str, parent: int) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return None


class FileArea:
    """Own opaque files beneath one trusted workspace root."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.database_path = root / _DATABASE_NAMES[0]

    @classmethod
    def create(cls, root: Path) -> "FileArea":
        with _file_errors():
            os.mkdir(root, mode=0o700)
            with _directory(root) as descriptor:
                os.mkdir("artifacts", mode=0o700, dir_fd=descriptor)
                os.fsync(descriptor)
            with _directory(root.parent) as parent:
                os.fsync(parent)
            return cls(root.resolve(strict=True))

    @classmethod
    def open(cls, root: Path) -> "FileArea":
        with _file_errors(), _directory(root) as descriptor:
            with _directory("artifacts", parent=descriptor):
                pass
            return cls(root.resolve(strict=True))

    def create_database_file(self) -> None:
        with _file_errors(), _directory(self.root) as root:
            descriptor = os.open(
                _DATABASE_NAMES[0],
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=root,
            )
            try:
                _regular(os.fstat(descriptor))
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.fsync(root)

    def check_database_files(self) -> None:
        with _file_errors(), _directory(self.root) as root:
            for name in _DATABASE_NAMES:
                info = _entry_info(name, root)
                if info is None:
                    if name == _DATABASE_NAMES[0]:
                        raise _failure(
                            ErrorCode.CORRUPT_WORKSPACE, "The workspace database is missing."
                        )
                    continue
                _regular(info, allow_unlinked=name != _DATABASE_NAMES[0])
                try:
                    descriptor = os.open(name, _FILE_FLAGS, dir_fd=root)
                except FileNotFoundError:
                    if name == _DATABASE_NAMES[0]:
                        raise
                    continue
                try:
                    _regular(os.fstat(descriptor), allow_unlinked=name != _DATABASE_NAMES[0])
                finally:
                    os.close(descriptor)

    @contextmanager
    def _session(self, session_id: SessionId, *, create: bool = False) -> Iterator[int]:
        with _file_errors(), _directory(self.root) as root:
            with _directory("artifacts", parent=root) as artifacts:
                if create:
                    _make_directory(str(session_id), artifacts)
                with _directory(str(session_id), parent=artifacts) as session:
                    yield session

    def write(self, artifact: ArtifactRef, source: BinaryIO) -> None:
        """Publish flushed content while the caller holds its database writer lock."""
        pending = f"{artifact.artifact_id}.pending"
        final = f"{artifact.artifact_id}.data"
        with _file_errors(), self._session(artifact.session_id, create=True) as session:
            for name in (final, pending):
                info = _entry_info(name, session)
                if info is not None:
                    _regular(info)
                    raise _failure(ErrorCode.CONFLICT, "The artifact file already exists.")
            descriptor = os.open(
                pending,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=session,
            )
            with os.fdopen(descriptor, "wb") as destination:
                try:
                    shutil.copyfileobj(source, destination)
                except Exception as exc:
                    raise _failure(
                        ErrorCode.STORAGE_FAILED, "The artifact stream could not be copied."
                    ) from exc
                destination.flush()
                os.fchmod(destination.fileno(), 0o400)
                os.fsync(destination.fileno())
            # The database writer lock excludes competing artifact publication.
            os.rename(pending, final, src_dir_fd=session, dst_dir_fd=session)
            os.fsync(session)

    def _read_handle(self, artifact: ArtifactRef) -> BinaryIO:
        with _file_errors(), self._session(artifact.session_id) as session:
            descriptor = os.open(f"{artifact.artifact_id}.data", _FILE_FLAGS, dir_fd=session)
            try:
                _regular(os.fstat(descriptor))
                return os.fdopen(descriptor, "rb")
            except Exception:
                os.close(descriptor)
                raise

    @contextmanager
    def reader(self, artifact: ArtifactRef) -> Iterator[BinaryIO]:
        """Provide a read-only handle without returning an internal file path."""
        with _file_errors(), self._read_handle(artifact) as stream:
            yield stream

    def check(self, artifact: ArtifactRef) -> None:
        with self.reader(artifact):
            pass

    @staticmethod
    def _recovery_entry(name: str, session: int) -> tuple[ArtifactId, str]:
        stem, separator, suffix = name.rpartition(".")
        if not separator or suffix not in ("pending", "data"):
            raise _failure(
                ErrorCode.CORRUPT_WORKSPACE, "The artifact directory contains an unknown entry."
            )
        try:
            artifact_id = ArtifactId(stem)
        except ValidationError as exc:
            raise _failure(
                ErrorCode.CORRUPT_WORKSPACE, "An artifact filename has an invalid identifier."
            ) from exc
        _regular(os.stat(name, dir_fd=session, follow_symlinks=False))
        return artifact_id, suffix

    def reconcile(
        self, session_id: SessionId, known: frozenset[ArtifactId]
    ) -> tuple[ArtifactId, ...]:
        """Remove recognized unreachable files under the caller's database writer lock."""
        removed: set[ArtifactId] = set()
        try:
            with _file_errors(), self._session(session_id, create=True) as session:
                entries = [
                    (name, *self._recovery_entry(name, session))
                    for name in sorted(os.listdir(session))
                ]
                for name, artifact_id, suffix in entries:
                    if suffix == "pending" or artifact_id not in known:
                        os.unlink(name, dir_fd=session)
                        removed.add(artifact_id)
                if removed:
                    os.fsync(session)
        except ContractError as exc:
            if removed:
                raise ContractError(
                    Error(
                        code=exc.error.code,
                        message=exc.error.message,
                        effect=MutationEffect.UNKNOWN,
                    )
                ) from exc
            raise
        return tuple(sorted(removed, key=str))
