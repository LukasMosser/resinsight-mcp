"""Reserve protocol output before running services in a dedicated stdio process."""

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TextIO

import anyio
from mcp.server.stdio import stdio_server

from .catalog import Bindings
from .server import create_server


@contextmanager
def _protocol_output() -> Iterator[TextIO]:
    """Send Python, native, and inherited child stdout to application stderr."""
    sys.stdout.flush()
    descriptor = sys.stdout.fileno()
    with os.fdopen(os.dup(descriptor), "w", encoding="utf-8") as protocol:
        try:
            os.dup2(sys.stderr.fileno(), descriptor)
            yield protocol
        finally:
            sys.stdout.flush()
            os.dup2(protocol.fileno(), descriptor)


async def serve_stdio(bindings: Bindings) -> None:
    """Run one dedicated protocol process without closing service sessions on disconnect."""
    with _protocol_output() as protocol:
        server = create_server(bindings)
        async with stdio_server(stdout=anyio.wrap_file(protocol)) as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())
