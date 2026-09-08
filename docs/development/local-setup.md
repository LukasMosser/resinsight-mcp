# Local setup

The development environment uses Python 3.12 and uv.
A lockfile records the dependency versions for this environment.
The project installs its contracts, workspace storage, and session coordination from the checkout.
The base runtime includes Pydantic and psutil for records and process inspection.
The optional `resinsight` extra adds rips.
The [session guide](../sessions.md) explains native application requirements and installation.

From the repository directory, install the package and locked development dependencies:

```sh
uv sync --locked --all-groups
```

Install the Git hooks:

```sh
uv run --locked pre-commit install
```

A Git hook runs an automated command during a Git operation.
The hooks catch local problems before review.
They do not replace the complete repository quality gate.

Run the repository quality gate:

```sh
uv run --locked python scripts/check.py
```

The shared command runs Ruff, ty, pytest, and the strict documentation build.
To run only the maintained library tests, use:

```sh
uv run --locked pytest
```

These tests exercise library behavior and separate local processes that implement the upstream remote call protocol.
They do not launch ResInsight or a simulator.
The [contract guide](contracts.md) explains records, interfaces, and serialization.
The [workspace guide](workspaces.md) includes an example using a temporary local directory.
The [P04 record](p04-evidence.md) reports the separate real application acceptance trial.
Job tests launch small Python process groups and real MCP connections.
The [P10 record](p10-evidence.md) describes their cancellation, restart, and failure evidence.
Workspace operations require a trusted local macOS or Linux filesystem with supported directory and synchronization operations.
The [P01 record](platform-proof.md) contains the separate external runtime evidence.

To preview the documentation, start the local server:

```sh
uv run --locked mkdocs serve
```

Open the local address that MkDocs prints.
To stop the server, press `Ctrl+C`.
If a command fails, read its output before changing files or dependencies.

The preview uses MathJax to display LaTeX notation.
Your browser needs network access to load MathJax from its content delivery network.
This formula provides a visible rendering sample:

\[
\Delta p = p_{\mathrm{final}} - p_{\mathrm{initial}}
\]

Here, \(p\) is pressure and \(\Delta p\) is its change.
Use the same units for both pressure values.
This example tests notation rendering and does not describe implemented simulation behavior.
