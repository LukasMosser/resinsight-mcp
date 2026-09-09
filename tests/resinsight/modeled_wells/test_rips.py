"""Check native completion values through the maintained backend boundary."""

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest

from resinsight_mcp.contracts.errors import ContractError, ErrorCode, MutationEffect
from resinsight_mcp.contracts.identifiers import ConnectionId, SessionId
from resinsight_mcp.contracts.sessions import ApplicationContext, ProjectState
from resinsight_mcp.resinsight.sessions._backend import ApplicationAccess
from resinsight_mcp.resinsight.sessions.rips import RipsApplication
from resinsight_mcp.resinsight.wells import RipsWellBackend


class CompletionApplication(RipsApplication):
    def __init__(self, reference_depth: object) -> None:
        self.reference_depth = reference_depth

    def call[T](self, action: Callable[[], T], *, mutation: bool = False) -> T:
        assert not mutation
        return action()

    def project(self) -> Any:
        head = SimpleNamespace(well_name="PROD", grid_name="", grid_i=5, grid_j=5)
        connection = SimpleNamespace(
            well_name="PROD",
            grid_name="",
            grid_i=5,
            grid_j=5,
            upper_k=1,
            lower_k=1,
            open_shut_flag="OPEN",
            transmissibility=10.078780273272798,
            kh=9500.0,
            diameter=0.5,
            skin_factor=0.0,
            direction="Z",
            start_md=8326.0,
            end_md=8345.0,
        )
        well = SimpleNamespace(
            address=lambda: 2,
            name="PROD",
            completion_settings=lambda: SimpleNamespace(
                reference_depth_for_export=self.reference_depth
            ),
            completion_data=lambda *, case_id: SimpleNamespace(
                welspecs=[head], compdat=[connection]
            ),
        )
        return SimpleNamespace(
            cases=lambda: [SimpleNamespace(address=lambda: 1, id=0)], well_paths=lambda: [well]
        )


def access(reference_depth: object) -> ApplicationAccess:
    context = ApplicationContext(
        session_id=SessionId.new(), connection_id=ConnectionId.new(), project_generation=0
    )
    return ApplicationAccess(
        CompletionApplication(reference_depth), ProjectState(context=context), ()
    )


@pytest.mark.parametrize("native_depth, expected", [("", None), (None, None), (8335.0, 8335.0)])
def test_completion_export_preserves_optional_native_reference_depth(
    native_depth: object, expected: float | None
) -> None:
    exported = RipsWellBackend().completions(access(native_depth), "1", "2")
    assert exported.wellhead.reference_depth_ft == expected
    assert (exported.wellhead.i, exported.wellhead.j) == (4, 4)
    assert exported.connections[0].permeability_length_md_ft == 9500.0


def test_invalid_native_reference_depth_fails_before_mutation() -> None:
    with pytest.raises(ContractError) as failure:
        RipsWellBackend().completions(access("invalid"), "1", "2")
    assert failure.value.error.code == ErrorCode.EXECUTION_FAILED
    assert failure.value.error.effect == MutationEffect.NOT_APPLIED
