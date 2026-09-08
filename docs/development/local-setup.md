# Local setup

The development environment uses Python 3.12 and uv.
A lockfile records the dependency versions for this environment.
The repository is a virtual project, which manages tools without installing an application package.

From the repository directory, install the locked development dependencies:

```sh
uv sync --locked --all-groups
```

Install the Git hooks:

```sh
uv run pre-commit install
```

A Git hook runs an automated command during a Git operation.
The hooks catch local problems before review.
They do not replace the complete repository quality gate.

Run the repository quality gate:

```sh
uv run --locked python scripts/check.py
```

To preview the documentation, start the local server:

```sh
uv run mkdocs serve
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
