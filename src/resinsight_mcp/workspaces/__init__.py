"""Durable local workspaces with immutable input revisions."""

from .store import SqliteWorkspaceStore

__all__ = ["SqliteWorkspaceStore"]
