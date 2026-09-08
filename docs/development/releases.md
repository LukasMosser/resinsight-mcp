# Releases

The repository has no application release process to execute yet.
The documentation remains unpublished until the repository owner decides to make it public.
This page defines the proposed release evidence.
A documentation build alone does not establish a working MCP server.

Before proposing a release, prepare this evidence:

- Identify the exact commit and proposed version.
- Run the repository quality gate from a clean checkout with locked dependencies.
- Record the commands, environment, results, and unresolved failures.
- Review the documentation against the implemented behavior.
- Record dependency and license decisions for the shipped files.
- Describe user-visible changes and known limits.

For a release with external integrations, include runtime evidence.
Record the supported application, client, simulator, and operating system versions.
Make sure that the release description distinguishes tested combinations from proposed support.

For simulation support, retain the model revision and run inputs with the results.
For visual support, demonstrate that the actual agent client receives native image content.
A screenshot displayed in an interface does not establish that the model receives visual input.

Submit the evidence for maintainer review before publication.
If a required result fails, resolve the failure before marking the release ready.
Publish only after the repository owner approves public publication and the maintainer approves the release evidence.
