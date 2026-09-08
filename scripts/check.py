"""Run the same repository checks locally and in GitHub Actions."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMMANDS = (
    ("ruff", "check", "."),
    ("ruff", "format", "--check", "."),
    ("ty", "check"),
    (sys.executable, "-m", "pytest", "-q"),
    ("mkdocs", "build", "--strict"),
)


def main() -> int:
    for command in COMMANDS:
        print(f"\nRun: {' '.join(command)}", flush=True)
        result = subprocess.run(command, cwd=ROOT, check=False)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
