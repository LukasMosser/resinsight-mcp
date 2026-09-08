# Local setup

The development environment uses Python 3.12 and uv.
A lockfile records the dependency versions for this environment.
The project installs its Python contracts package from the checkout.
Its runtime requirement is `pydantic>=2.13.5,<3`, with the exact compatible version recorded in the lockfile.
The package does not start an MCP server or connect to external applications.

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
To run only the maintained contract tests, use:

```sh
uv run --locked pytest
```

These tests exercise library behavior without starting ResInsight or a simulator.
The [contract guide](contracts.md) explains records, interfaces, and serialization.
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
