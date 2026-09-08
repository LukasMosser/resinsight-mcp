"""Project records preserve context and safe path defaults."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from resinsight_mcp.contracts.identifiers import ConnectionId
from resinsight_mcp.contracts.sessions import (
    ApplicationContext,
    ObjectKind,
    ObjectRef,
    ProjectObject,
    ProjectOpenRequest,
    ProjectSaveRequest,
    ProjectState,
)


def test_project_records_round_trip_and_save_requires_explicit_overwrite(
    context: ApplicationContext, tmp_path: Path
) -> None:
    item = ProjectObject(
        ref=ObjectRef(context=context, kind=ObjectKind.VIEW, object_id="opaque"), name="View"
    )
    state = ProjectState(context=context, objects=(item,), last_saved_path=tmp_path / "saved.rsp")
    assert ProjectState.model_validate_json(state.model_dump_json()) == state
    assert not ProjectSaveRequest(context=context, path=tmp_path / "saved.rsp").overwrite


@pytest.mark.parametrize("record", [ProjectOpenRequest, ProjectSaveRequest])
def test_project_request_rejects_relative_path(
    context: ApplicationContext, record: type[ProjectOpenRequest]
) -> None:
    with pytest.raises(ValidationError):
        record(context=context, path=Path("relative.rsp"))


def test_project_state_rejects_mixed_context_and_duplicate_reference(
    context: ApplicationContext,
) -> None:
    other = context.model_copy(update={"connection_id": ConnectionId.new()})
    item = ProjectObject(
        ref=ObjectRef(context=other, kind=ObjectKind.CASE, object_id="opaque"), name="Case"
    )
    with pytest.raises(ValidationError, match="current application context"):
        ProjectState(context=context, objects=(item,))
    with pytest.raises(ValidationError, match="unique"):
        ProjectState(context=other, objects=(item, item))
