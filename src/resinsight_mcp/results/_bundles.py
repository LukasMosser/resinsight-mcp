"""Keep result files at stable paths for saved native projects."""

import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from resinsight_mcp.contracts.errors import ErrorCode
from resinsight_mcp.contracts.interfaces import WorkspaceStore
from resinsight_mcp.contracts.jobs import Result
from resinsight_mcp.contracts.results import ResultManifest, ResultOutput, ResultOutputRole
from resinsight_mcp.contracts.workspace import ArtifactKind

from ._common import fail, value


@dataclass(frozen=True)
class ResultBundle:
    result: Result
    directory: Path
    egrid: Path
    smspec: Path


def regular(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        fail(ErrorCode.INVALID_PATH, "Result bundle files must be regular files with one link.")


def directory(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        fail(ErrorCode.INVALID_PATH, "The result bundle directory must be a real directory.")
    if any(parent.is_symlink() for parent in path.parents):
        fail(ErrorCode.INVALID_PATH, "Result bundle ancestors cannot be symbolic links.")


class Bundles:
    def __init__(self, workspaces: WorkspaceStore, root: Path) -> None:
        if not root.is_absolute():
            fail(ErrorCode.INVALID_PATH, "The result bundle root must be absolute.")
        root.mkdir(parents=True, exist_ok=True)
        directory(root)
        self.root = root
        self.workspaces = workspaces

    def materialize(self, result: Result) -> ResultBundle:
        manifest = result.manifest
        if manifest is None:
            fail(ErrorCode.INVALID_MODEL, "The result has no output manifest.")
        parent = self.root / str(result.model.session_id)
        parent.mkdir(exist_ok=True)
        directory(parent)
        target = parent / str(result.result_id)
        files = self._files(manifest)
        if target.exists() or target.is_symlink():
            directory(target)
            regular(target / "manifest.json")
            if (
                ResultManifest.model_validate_json((target / "manifest.json").read_text())
                != manifest
            ):
                fail(ErrorCode.CONFLICT, "The existing bundle belongs to another output manifest.")
        else:
            temporary = Path(tempfile.mkdtemp(prefix=".result-", dir=parent))
            try:
                for output, name in files:
                    with self.workspaces.open_artifact(output.artifact) as source:
                        with (temporary / name).open("xb") as destination:
                            shutil.copyfileobj(source, destination)
                (temporary / "manifest.json").write_text(
                    manifest.model_dump_json(), encoding="utf-8"
                )
                temporary.rename(target)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
        for _, name in files:
            regular(target / name)
        paths = {output.role: target / name for output, name in files}
        return ResultBundle(
            result, target, paths[ResultOutputRole.EGRID], paths[ResultOutputRole.SMSPEC]
        )

    def _files(self, manifest: ResultManifest) -> tuple[tuple[ResultOutput, str], ...]:
        files = []
        for output in manifest.outputs:
            artifact = value(self.workspaces.get_artifact(output.artifact))
            if artifact.kind != ArtifactKind.OUTPUT:
                fail(ErrorCode.INVALID_MODEL, "Result files require output artifacts.")
            name = Path(artifact.relative_path).name
            if Path(name).suffix.upper() != "." + output.role.value.upper():
                fail(ErrorCode.INVALID_MODEL, "The result filename differs from its output role.")
            files.append((output, name))
        if len({Path(name).stem for _, name in files}) != 1:
            fail(ErrorCode.INVALID_MODEL, "Native result files must share one case basename.")
        return tuple(files)
