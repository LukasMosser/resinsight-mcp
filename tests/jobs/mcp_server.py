"""Production MCP transport with a trusted, fixed acceptance command."""

import asyncio
import sys
from pathlib import Path

from resinsight_mcp.jobs import DurableJobController, JobCommand
from resinsight_mcp.mcp import Bindings, serve_stdio

COMPLETE = """
from pathlib import Path
import time
with Path('executions.txt').open('a') as count:
    count.write('started\\n')
Path('ready').touch()
deadline = time.monotonic() + 8
while not Path('release').exists():
    if time.monotonic() >= deadline:
        raise RuntimeError('The acceptance client did not release the command.')
    time.sleep(0.02)
print('The original job completed after reconnect.')
"""

CANCEL = """
from pathlib import Path
import json, subprocess, sys, time
child = subprocess.Popen([sys.executable, '-c',
    "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(10)"])
Path('child.json').write_text(json.dumps(child.pid))
Path('ready').touch()
time.sleep(10)
"""


async def main() -> None:
    root = Path(sys.argv[1])
    command = {"complete": COMPLETE, "cancel": CANCEL}[sys.argv[2]]
    jobs = DurableJobController(
        root,
        lambda request: JobCommand(argv=(sys.executable, "-c", command), working_directory=root),
    )
    await serve_stdio(Bindings(workspaces=jobs.store, jobs=jobs))


if __name__ == "__main__":
    asyncio.run(main())
