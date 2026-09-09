Shipped launcher acceptance evidence

The installed package came from clean source 8470225cf74edb8a592a47d4777c7c4f03c98c58.
The acceptance runner is retained in tests/acceptance/launcher/run.py in this change.
The runner was added after the package installation.
It does not alter the installed application package.

The install command and log record a fresh noneditable environment from the existing lockfile.
The environment record identifies the installed package path, versions, and native build.
The events file retains all public tool requests, responses, discovery results, and process checks.
The acceptance log preserves the runner's output.
The native-logs directory retains the launched application's log and endpoint file.
The native-build record retains the existing P01 configuration and OpenZGY overlay limits.

The input project is the archived docs/development/evidence/p04/P04 first.rsp.
The project-input record verifies its referenced local files and directory before use.
The saved-project.rsp file is the result of the public project_save operation.
The images directory contains one independently captured native snapshot.
Its original filename remains unchanged.

The trial completed 18 public tool calls and exited with status zero.
The application survived protocol disconnect and public detach.
Cleanup checked the original lifetime, executable, command, and endpoint before native Exit.
The cleanup_completed event records confirmed process termination.

The package omits the local workspace database, installed environment, client working directory, and duplicate input project.
Those paths remain in the raw records for traceability.
No MCP view tools, simulator execution, model-provider acceptance, or issue 34 editor inspection ran.
