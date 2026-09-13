"""Expose immutable simulator assembly and isolated OPM input validation."""

from typing import Any

from resinsight_mcp.contracts.errors import OperationResult
from resinsight_mcp.contracts.models import ArtifactRef
from resinsight_mcp.models.general.compilation.records import (
    AssemblyInfo,
    AssemblyPage,
    AssemblyPageRequest,
    AssemblyRequest,
    PreparedSimulation,
)

from .catalog import Bindings, Operation


def compilation_operations(bindings: Bindings) -> tuple[Operation[Any, Any], ...]:
    service = bindings.general_compilation
    if service is None:
        return ()
    return (
        Operation(
            "general_simulation_define",
            "Assemble physics, schedules, and compatible native connection exports.",
            AssemblyRequest,
            OperationResult[AssemblyInfo],
            service.define,
            read_only=False,
        ),
        Operation(
            "general_simulation_inspect",
            "Read compact assembly lineage and input completeness.",
            ArtifactRef,
            OperationResult[AssemblyInfo],
            service.inspect,
            read_only=True,
        ),
        Operation(
            "general_simulation_exports",
            "Read a bounded page of the assembly's native connection bindings.",
            AssemblyPageRequest,
            OperationResult[AssemblyPage],
            service.exports,
            read_only=True,
        ),
        Operation(
            "general_simulation_prepare",
            "Compile an immutable input bundle and validate it with isolated OPM 2025.10.",
            ArtifactRef,
            OperationResult[PreparedSimulation],
            service.prepare,
            read_only=False,
        ),
        Operation(
            "general_simulation_prepared",
            "Read a validated input receipt without claiming simulator execution.",
            ArtifactRef,
            OperationResult[PreparedSimulation],
            service.prepared,
            read_only=True,
        ),
    )
