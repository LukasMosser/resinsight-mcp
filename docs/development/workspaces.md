# Workspaces

`SqliteWorkspaceStore` stores durable engineering records and immutable artifact files.
SQLite is an embedded database stored in one local file.
The public class is available from `resinsight_mcp.workspaces`.
It implements the shared `WorkspaceStore` interface without starting ResInsight, a simulator, or an MCP server.

## Supported boundary

The store targets trusted local macOS and Linux filesystems.
The workspace owner must control the root and its metadata directories.
Artifact access uses directory-relative handles that reject observed symbolic links, hard links, and nonregular files.
These checks do not protect against an owner concurrently rewriting database files or replacing trusted directories.
Network filesystems, shared remote users, and Windows storage are outside this implementation's supported boundary.

Artifacts remain opaque streams to the store.
It does not parse simulator inputs, decode images, calculate content hashes, or detect changes made outside its API.
File identities and read-only access preserve references within the API, without proving external file contents.

## Create and reopen

`SqliteWorkspaceStore.create(root)` requires a new directory under an existing parent.
It rejects an existing root instead of reusing or overwriting it.
`SqliteWorkspaceStore.open(root)` opens an existing compatible workspace and checks its database.
Opening does not reconcile artifacts or change job states.
Each operation opens and closes its own database connection, so the store has no close method.

Both methods accept `timeout=5.0`, measured in seconds, for SQLite lock waits.
The timeout must be finite and nonnegative.
A lock timeout reports `busy` through the operation's error boundary.
Python documents the underlying lock-wait behavior in [sqlite3.connect](https://docs.python.org/3.12/library/sqlite3.html#sqlite3.connect).

Creation and opening raise `ContractError` for storage failures.
Most other public methods return `OperationResult[T]`, containing either `Success[T]` or `Failure`.
`open_artifact()` instead returns a read-only binary context manager and raises `ContractError` for file failures.
Record construction uses Pydantic validation errors, and an invalid timeout raises `ValueError`.

## Runnable example

Save this example as `workspace_example.py` outside the package source.
Run it with `uv run --locked python workspace_example.py` from the repository environment.
It creates a temporary workspace, stores a JSON input, clones its revision, and reopens the stored records.
The JSON is demonstration data, not a simulator input model.
The temporary directory is removed when the example finishes.

```python
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from resinsight_mcp.contracts.engineering import (
    CoordinateFrame,
    DepthDirection,
    ModelRef,
    Unit,
    UnitSystem,
)
from resinsight_mcp.contracts.errors import ContractError, Failure, OperationResult
from resinsight_mcp.contracts.identifiers import ArtifactId, RevisionId, SessionId
from resinsight_mcp.contracts.models import ArtifactRef, ModelInputs, ModelRevision, Session
from resinsight_mcp.contracts.workspace import Artifact, ArtifactKind
from resinsight_mcp.workspaces import SqliteWorkspaceStore


def require[T](result: OperationResult[T]) -> T:
    if isinstance(result.outcome, Failure):
        raise ContractError(result.outcome.error)
    return result.outcome.value


with TemporaryDirectory() as temporary:
    root = Path(temporary) / "workspace"
    store = SqliteWorkspaceStore.create(root)
    session = Session(session_id=SessionId.new(), name="Storage example")
    require(store.create_session(session))
    original = Artifact(
        ref=ArtifactRef(session_id=session.session_id, artifact_id=ArtifactId.new()),
        relative_path="model.json",
        kind=ArtifactKind.INPUT,
    )
    require(store.write_artifact(original, io.BytesIO(json.dumps({"rate": 10}).encode())))
    revision = ModelRevision(
        model=ModelRef(session_id=session.session_id, revision_id=RevisionId.new()),
        inputs=ModelInputs(
            artifacts=(original.ref.artifact_id,),
            entrypoint=original.ref.artifact_id,
        ),
        unit_system=UnitSystem.METRIC,
        coordinates=CoordinateFrame(
            length_unit=Unit.METER,
            depth_direction=DepthDirection.POSITIVE_DOWN,
            datum="Local origin",
        ),
    )
    require(store.save_revision(revision))
    replacement = Artifact(
        ref=ArtifactRef(session_id=session.session_id, artifact_id=ArtifactId.new()),
        relative_path="model.json",
        kind=ArtifactKind.INPUT,
    )
    require(store.write_artifact(replacement, io.BytesIO(json.dumps({"rate": 20}).encode())))
    clone = require(
        store.clone_revision(
            revision.model,
            RevisionId.new(),
            replacements=(replacement.ref.artifact_id,),
        )
    )
    reopened = SqliteWorkspaceStore.open(root)
    assert require(reopened.get_revision(revision.model)) == revision
    assert require(reopened.get_revision(clone.model)).parent == revision.model
    with reopened.open_artifact(original.ref) as source:
        original_rate = json.load(source)["rate"]
    with reopened.open_artifact(replacement.ref) as source:
        clone_rate = json.load(source)["rate"]
    print(f"Original rate: {original_rate}; clone rate: {clone_rate}")
```

The output is `Original rate: 10; clone rate: 20`.
The original revision and its artifact remain unchanged.
This example reopens through another store object in one process.
Fresh-process persistence and concurrent access require separate acceptance tests.

## Stored records and lineage

Every record belongs to an explicit engineering session.
Record identities are qualified by that session and the workspace root.
A lookup does not search other workspaces or infer a selected session.
`JobRef` supplies both the session and job identifiers for `get_job()`.

The store provides these record operations:

| Records | Operations |
| --- | --- |
| Sessions | Create, get, and list. |
| Artifacts | Write a new file, get metadata, list metadata, and open a read-only stream. |
| Revisions | Save, get, and clone with a new identity. |
| Jobs | Save with an expected prior record, get, and list. |
| Results and observations | Save and get by their explicit identities. |
| Project checkpoints | Save and get by session and checkpoint identifiers. |

Equal retries of immutable records return the stored record.
Changed content under the same identity reports `conflict`.
Artifact writes always reject an existing identity because the store does not compare file contents.
`list_artifacts()` returns committed metadata without checking every file's availability.
`get_artifact()` and `open_artifact()` require an accessible regular file.

Saving a result requires its exact stored revision and a succeeded job with matching model lineage.
Saving an observation requires the stored result context and an existing `IMAGE` artifact.
A stored observation does not establish that its declared PNG dimensions match decoded image data.
A later renderer must establish that external evidence.

## Input paths and immutable clones

Each `Artifact` has an `ArtifactKind` and a logical `relative_path`.
The kinds are `input`, `output`, `image`, `log`, and `project`.
Relative paths preserve model filenames and include-directory structure without becoming internal storage paths.
Absolute paths, empty segments, dot segments, backslashes, colons, and control characters are rejected.

A revision requires existing, readable `INPUT` artifacts and an entrypoint among them.
Input names cannot collide after Unicode NFC normalization and case-insensitive comparison.
NFC gives equivalent Unicode spellings a common form.
An input filename also cannot serve as another input's directory.
Reading a revision checks its artifacts and fails if an input is missing or inaccessible.

`clone_revision()` creates a new revision in the source session and records the source as its parent.
Unchanged inputs share their immutable artifact identities.
Replacement artifacts match the exact original relative path or add a new path.
A replacement of the entrypoint path changes the clone's entrypoint identity.
A different spelling that only matches after normalization or case folding is rejected as a collision.

The store does not edit a revision or artifact in place.
A changed input needs a new artifact identity and a new revision.
The clone retains the source's unit system and coordinate frame.
Simulator parsing and validation remain later model-import responsibilities.

## Project checkpoints

`ProjectCheckpoint` binds a stored revision to a supplied `PROJECT` artifact in the same session.
It also records a checkpoint identifier and a name.
The store requires the revision and project artifact to exist.
Reopening a checkpoint preserves that recorded relationship and checks file availability.

The caller supplies the project file and its claimed model relationship.
P03 does not save or open a ResInsight project or verify its contents against that revision.
P04 supplies the planned application lifecycle behavior.

## Job updates and explicit recovery

A new stored job must be `queued` without cancellation intent.
Changed jobs require `save_job(updated, expected=previous)` with the exact stored prior record.
Updates preserve model and backend identity, follow allowed transitions, and never clear cancellation intent.
Stale competing updates report `conflict` instead of replacing newer state.
An equal retry returns the current job without another change.

Before selecting recovery jobs, stop the job controller.
Then read the intended job snapshots and pass them as `expected_jobs` to `reconcile(session_id, expected_jobs=...)`.
The store checks every supplied snapshot inside the writer transaction before changing records or removing files.
A stale snapshot rejects the operation.
The store cannot verify that the caller stopped its controller.

Only supplied jobs participate in recovery.
Queued and running jobs become `unknown`, while unknown and terminal jobs remain unchanged.
Cancellation intent survives this transition.
An empty `expected_jobs` tuple leaves every job unchanged.
No process is inspected, signaled, or declared terminated.

Recovery removes recognized pending files and uncommitted artifact files only within the requested session.
An uncommitted file has no artifact metadata record.
Committed files remain, including artifacts that no revision currently references.
Unknown filenames or unsafe entries cause a clear failure instead of being silently removed.

`RecoveryReport` contains the selected jobs, removed artifact identifiers, and unavailable committed artifacts with their errors.
Missing files remain missing and are reported without replacement data.
Unsafe directory entries can prevent the recovery operation from returning a report.
A partial cleanup failure reports `unknown` mutation effect because deleted files cannot be restored by a database rollback.

## Publication and schema policy

A transaction groups database changes into one commit or rollback.
Writers hold a SQLite `BEGIN IMMEDIATE` transaction through artifact publication or recovery.
The database uses rollback-journal mode with `synchronous=FULL`.
Other store writers wait for that lock, subject to their configured timeout.

SQLite can delete a journal while another operation checks its file metadata.
Database sidecars are SQLite's temporary files beside the database.
Their pathname and handle checks accept regular files with zero or one link during deletion.
The main database and artifact files still require exactly one link.
The [journal race evidence](evidence/workspace-journal/README.md) records the observed failure and the public-read regression for [issue 31](https://github.com/LukasMosser/resinsight-mcp/issues/31).

An artifact write creates an exclusive `.pending` file, copies the source, flushes it, and calls `fsync`.
The store marks the file read-only, renames it to `.data`, and synchronizes the directory before committing artifact metadata.
Python documents buffered flushing and synchronization in [os.fsync](https://docs.python.org/3.12/library/os.html#os.fsync).
The rename relies on the writer lock and trusted workspace ownership to exclude competing publication.

SQLite metadata and artifact files do not share one filesystem transaction.
An interruption can leave a pending file or a published file without committed metadata.
The public API does not expose those files as artifacts until their metadata commits.
Explicit recovery removes them later.
A stream failure never substitutes empty or previous content.

These synchronization steps do not establish immunity to power loss or storage hardware failure.
Durability depends on the operating system and filesystem honoring synchronization requests, as described in [SQLite's atomic commit documentation](https://www.sqlite.org/atomiccommit.html).
The maintained tests do not substitute for power-loss testing on a specific storage device.

Schema version 1 is the first supported workspace schema.
The database carries application marker `0x524D4350` and required table, key, and session-relationship definitions.
Opening rejects other versions, incompatible journal modes, or unsupported metadata without migration or overwrite.
Stored JSON records are validated when read, including their session and record identities.
The store does not repair an unrelated or corrupt database.

## Source and on-disk layout

The workspace package is `src/resinsight_mcp/workspaces/`.
Its files separate these responsibilities:

| Source file | Responsibility |
| --- | --- |
| `__init__.py` | Export the public store class. |
| `store.py` | Public operations and record relationships. |
| `_database.py` | SQLite connections, schema checks, and transactions. |
| `_records.py` | Typed JSON serialization and session-qualified record keys. |
| `_files.py` | Artifact streams, safe file access, publication, and cleanup. |

The shared records live in `src/resinsight_mcp/contracts/workspace.py`.
The private modules are implementation details, not additional public APIs.
A workspace uses this layout:

```text
workspace/
  workspace.sqlite3
  artifacts/
    <session_id>/
      <artifact_id>.data
      <artifact_id>.pending
```

SQLite can create temporary journal files beside the database.
A `.pending` file can remain after an interrupted write.
Logical artifact names such as `includes/rock.inc` are stored in metadata, not expanded beneath this directory.
Use the public store methods to access files and records.

## Errors

| Code | Workspace condition |
| --- | --- |
| `conflict` | An existing immutable identity, duplicate artifact write, or stale expected job record conflicts with the request. |
| `invalid_path` | An observed link or nonregular file prevents safe access. |
| `invalid_model` | A submitted record has invalid relationships, artifact kinds, input names, or lineage. |
| `invalid_transition` | A job update violates state or cancellation rules. |
| `not_found` | A requested record or artifact file is missing. |
| `busy` | A SQLite lock prevents the operation within its timeout. |
| `storage_failed` | A stream, filesystem, or other database operation fails. |
| `corrupt_workspace` | Required database structure, stored records, or artifact directory entries are inconsistent. |
| `unsupported_schema` | The database version or journal mode is unsupported. |

Invalid artifact path strings fail record validation before file access.
A missing database is reported through the creation or opening error boundary, rather than replaced with a new database.
Errors with `not_applied` do not establish that interrupted writes left no unreachable files.
Commit uncertainty and partial recovery cleanup can report `unknown`.
Inspect current state before deciding whether a failed operation can be repeated.
