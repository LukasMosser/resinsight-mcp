# Releases

GitHub Releases holds published source versions and their release notes.
The repository contains a workflow that creates draft source releases.
The source includes shared contracts and durable workspace storage.
It does not provide an MCP server or a supported simulator runtime release.

## Prepare a source release

Prepare the version change in a pull request against `main`.
Make sure that the project version in `pyproject.toml` matches the intended `vMAJOR.MINOR.PATCH` tag.
Record the commands, environment, results, and unresolved limits in the PR.

Before merging, prepare this evidence:

- Run `uv run --locked python scripts/check.py` from a clean checkout.
- Review the documentation against the implemented behavior.
- Record dependency and license decisions for the distributed files.
- Describe user-visible changes and known limits.

After merge, create and push the version tag from the reviewed commit.
Run the `Draft source release` workflow from `main` with that tag.
The workflow requires an existing tag whose commit belongs to `main`.

The workflow makes sure that the tag matches the project version.
It runs the shared repository checks and creates a draft GitHub Release.
The draft contains source only and does not publish a package to PyPI.

Edit the draft notes to describe the actual change and link its evidence.
Make sure that the source tag still identifies the reviewed commit.
Publish after the maintainer accepts the release evidence.

## Application evidence

A source release does not establish a working MCP server.
For an application release, include evidence from the supported runtime workflow.
Record the application, client, simulator, and operating system versions.

For simulation support, retain the model revision and run inputs with the results.
For visual support, demonstrate that the actual client passes native images to the model.
The release description must distinguish tested combinations from proposed support.

## Documentation publication

GitHub Pages hosts the [project documentation](https://lukasmosser.github.io/resinsight-mcp/).
The `Documentation` workflow builds and deploys the site from `main`.
Deployment requires the repository variable `PAGES_ENABLED` to equal `true`.

To publish the current version again, run the `Documentation` workflow from `main`.
Make sure that the workflow succeeds and the deployed pages display correctly.
Include LaTeX notation in the browser inspection.
