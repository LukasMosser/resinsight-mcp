"""Run a public store operation in an independent process."""

import io
import json
import os
import sys
from pathlib import Path

from resinsight_mcp.contracts.errors import Success
from resinsight_mcp.contracts.jobs import Job, JobRef, Result
from resinsight_mcp.contracts.models import ArtifactRef, ModelRevision, Session
from resinsight_mcp.contracts.workspace import Artifact, ProjectCheckpoint
from resinsight_mcp.workspaces import SqliteWorkspaceStore


class InterruptedInput(io.BytesIO):
    """Exit after one read to interrupt a real artifact write."""

    def __init__(self) -> None:
        super().__init__(json.dumps({"incomplete": True}).encode("utf-8"))
        self.read_count = 0

    def read(self, size: int | None = -1, /) -> bytes:
        self.read_count += 1
        if self.read_count > 1:
            os._exit(23)
        return super().read(size)


def main() -> None:
    action, root, payload_path = sys.argv[1:]
    store = SqliteWorkspaceStore.open(Path(root))
    payload = json.loads(Path(payload_path).read_text())
    if action == "reopen":
        revision = ModelRevision.model_validate_json(json.dumps(payload["revision"]))
        clone = ModelRevision.model_validate_json(json.dumps(payload["clone"]))
        checkpoint = ProjectCheckpoint.model_validate_json(json.dumps(payload["checkpoint"]))
        artifact = ArtifactRef(
            session_id=revision.model.session_id, artifact_id=revision.inputs.entrypoint
        )
        with store.open_artifact(artifact) as stream:
            content = json.load(stream)
        print(
            json.dumps(
                {
                    "revision": store.get_revision(revision.model).model_dump(mode="json"),
                    "checkpoint": store.get_checkpoint(
                        revision.model.session_id, checkpoint.checkpoint_id
                    ).model_dump(mode="json"),
                    "content": content,
                    "clone": store.get_revision(clone.model).model_dump(mode="json"),
                }
            )
        )
    elif action == "reopen-result":
        result = Result.model_validate_json(json.dumps(payload))
        print(store.get_result(result.model.session_id, result.result_id).model_dump_json())
    elif action == "reopen-job":
        job = JobRef.model_validate_json(json.dumps(payload))
        print(store.get_job(job).model_dump_json())
    elif action == "interrupt":
        artifact_record = Artifact.model_validate_json(json.dumps(payload))
        store.write_artifact(artifact_record, InterruptedInput())
        raise RuntimeError("The input did not interrupt the write.")
    else:
        print("ready", flush=True)
        if sys.stdin.readline().strip() != "go":
            raise RuntimeError("The writer did not receive its start signal.")
        if action == "create-session":
            outcome = store.create_session(Session.model_validate_json(json.dumps(payload)))
        elif action == "update-job":
            expected = Job.model_validate_json(json.dumps(payload["expected"]))
            job = Job.model_validate_json(json.dumps(payload["job"]))
            outcome = store.save_job(job, expected=expected)
        else:
            raise RuntimeError("Unknown worker operation.")
        print(outcome.model_dump_json(), flush=True)
        if isinstance(outcome.outcome, Success):
            return


if __name__ == "__main__":
    main()
