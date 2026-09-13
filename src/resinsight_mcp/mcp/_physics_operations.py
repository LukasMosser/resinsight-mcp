"""Expose bounded fluid and initialization authoring through MCP."""

from typing import Any

from resinsight_mcp.contracts.errors import OperationResult
from resinsight_mcp.contracts.models import ArtifactRef
from resinsight_mcp.models.general.physics.records import (
    PhysicsCreate,
    PhysicsEdit,
    PhysicsInfo,
    PhysicsRegions,
    PhysicsSchema,
    SchemaRequest,
    TablePage,
    TablePageRequest,
)

from .catalog import Bindings, Operation


def physics_operations(bindings: Bindings) -> tuple[Operation[Any, Any], ...]:
    physics = bindings.general_physics
    if physics is None:
        return ()
    return (
        Operation(
            "general_physics_schema",
            "Read required table columns, units, and validation rules.",
            SchemaRequest,
            OperationResult[PhysicsSchema],
            physics.schema,
            read_only=True,
        ),
        Operation(
            "general_physics_create",
            "Start explicit regional fluid and initialization authoring.",
            PhysicsCreate,
            OperationResult[PhysicsInfo],
            physics.create,
            read_only=False,
        ),
        Operation(
            "general_physics_edit",
            "Publish a child with bounded table edits and optional region assignments.",
            PhysicsEdit,
            OperationResult[PhysicsInfo],
            physics.edit,
            read_only=False,
        ),
        Operation(
            "general_physics_inspect",
            "Read compact coverage counts and immutable physics lineage.",
            ArtifactRef,
            OperationResult[PhysicsInfo],
            physics.inspect,
            read_only=True,
        ),
        Operation(
            "general_physics_regions",
            "Read the three explicit region assignment references.",
            ArtifactRef,
            OperationResult[PhysicsRegions],
            physics.regions,
            read_only=True,
        ),
        Operation(
            "general_physics_tables",
            "Read a bounded page of table metadata and numeric column references.",
            TablePageRequest,
            OperationResult[TablePage],
            physics.tables,
            read_only=True,
        ),
    )
