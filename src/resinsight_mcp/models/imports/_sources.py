"""Collect include files without interpreting reservoir model content."""

import io
import re
import shlex
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from resinsight_mcp.contracts.errors import ContractError, Error, ErrorCode
from resinsight_mcp.contracts.identifiers import ArtifactId, SessionId
from resinsight_mcp.contracts.models import ArtifactRef
from resinsight_mcp.contracts.workspace import Artifact, ArtifactKind

from .records import IncludeEdge

MAX_FILES = 64
MAX_DEPTH = 16
MAX_CHARACTERS = 2_000_000
MAX_EXPANDED_FILES = 256
_DIRECTIVE = re.compile(
    r"^\s*(INCLUDE|PATHS|IMPORT|GDFILE|PYINPUT|PYACTION|END|ENDINC|SKIP|SKIP100|SKIP300|ENDSKIP)\b",
    re.I,
)


def invalid(message: str) -> ContractError:
    return ContractError(Error(code=ErrorCode.INVALID_MODEL, message=message))


def check_name(name: str) -> None:
    if "$" in name or not name.isascii():
        raise invalid("Input paths must use ASCII names without aliases.")
    try:
        Artifact(
            ref=ArtifactRef(session_id=SessionId.new(), artifact_id=ArtifactId.new()),
            relative_path=name,
            kind=ArtifactKind.INPUT,
        )
    except ValueError as error:
        raise invalid(f"Invalid input path: {name}.") from error


def _without_comment(line: str) -> str:
    quoted = False
    for index, character in enumerate(line):
        if character == "'":
            quoted = not quoted
        if not quoted and line[index : index + 2] == "--":
            return line[:index]
    return line


def _clean_lines(content: str) -> tuple[str, ...]:
    lines = []
    for line in content.split("\n"):
        cleaned = _without_comment(line).strip(" \t\r")
        if any(
            not character.isascii() or (ord(character) < 32 and character != "\t")
            for character in cleaned
        ):
            raise invalid("Model text requires ASCII characters and ordinary spaces or tabs.")
        if "," in cleaned or cleaned.count("'") % 2:
            raise invalid("Comma separators and strings across lines are unsupported.")
        lines.append(cleaned)
    return tuple(lines)


def _include_record(lines: Iterator[str]) -> str:
    record = ""
    for part in lines:
        record += part + "\n"
        if "/" not in record:
            continue
        lexer = shlex.shlex(io.StringIO(record), posix=False, punctuation_chars="/")
        lexer.whitespace_split = True
        lexer.commenters = ""
        lexer.escape = ""
        try:
            tokens = list(lexer)
        except ValueError as error:
            raise invalid("An INCLUDE path has invalid quotes.") from error
        if tokens and tokens[-1] == "/":
            break
    else:
        raise invalid("An INCLUDE record must end with a slash.")
    if len(tokens) != 2 or not tokens[0].startswith("'") or not tokens[0].endswith("'"):
        raise invalid("INCLUDE requires one single-quoted path and a slash.")
    path = tokens[0][1:-1]
    check_name(path)
    return path


def include_paths(lines: tuple[str, ...]) -> tuple[str, ...]:
    """Accept standalone INCLUDE directives with one single-quoted path."""
    paths = []
    iterator = iter(lines)
    for cleaned in iterator:
        match = _DIRECTIVE.match(cleaned)
        if match is None:
            continue
        if match[1].upper() != "INCLUDE":
            raise invalid(f"The {match[1].upper()} file directive is unsupported.")
        if cleaned != "INCLUDE":
            raise invalid("INCLUDE must occupy its own uppercase line.")
        paths.append(_include_record(iterator))
    return tuple(paths)


def _check_collision(name: str, names: list[str]) -> None:
    key = name.casefold()
    for previous in names:
        other = previous.casefold()
        if key == other or key.startswith(other + "/") or other.startswith(key + "/"):
            raise invalid("Input paths must not collide across supported filesystems.")


@dataclass
class _Collector:
    root: Path
    target: Path
    names: list[str] = field(default_factory=list)
    edges: list[IncludeEdge] = field(default_factory=list)
    children: dict[str, tuple[str, ...]] = field(default_factory=dict)
    sizes: dict[str, int] = field(default_factory=dict)
    repetitions: dict[str, int] = field(default_factory=dict)
    active: set[str] = field(default_factory=set)
    total: int = 0

    def visit(self, name: str) -> None:
        if name in self.active:
            raise invalid(f"The include graph contains a cycle at {name}.")
        if name in self.names:
            return
        if len(self.names) >= MAX_FILES or len(self.active) >= MAX_DEPTH:
            raise invalid("The include graph exceeds the file or depth limit.")
        _check_collision(name, self.names)
        content = self.read(name)
        lines = _clean_lines(content)
        self.children[name] = include_paths(lines)
        self.sizes[name] = len(content)
        self.repetitions[name] = sum(
            int(match[1]) for line in lines for match in re.finditer(r"([0-9]+)\*", line)
        )
        self.names.append(name)
        self.active.add(name)
        destination = self.target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8", newline="") as stream:
            stream.write(content)
        for child in self.children[name]:
            self.edges.append(IncludeEdge(source=name, target=child))
            self.visit(child)
        self.active.remove(name)

    def read(self, name: str) -> str:
        path = self.root / name
        if any(part.is_symlink() for part in (path, *path.parents)) or not path.is_file():
            raise invalid(f"Input {name} is missing, is not a regular file, or uses a symlink.")
        with path.open(encoding="utf-8", newline="") as stream:
            content = stream.read(MAX_CHARACTERS - self.total + 1)
        self.total += len(content)
        if self.total > MAX_CHARACTERS:
            raise invalid("Input text exceeds 2,000,000 characters.")
        return content


def collect(
    root: Path, entrypoint: str, target: Path
) -> tuple[tuple[str, ...], tuple[IncludeEdge, ...]]:
    """Snapshot each source once and resolve includes against the DATA directory."""
    check_name(entrypoint)
    if "/" in entrypoint:
        raise invalid("Place the entrypoint directly inside the source root.")
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise invalid("The source root must be an absolute local directory without a symlink.")
    collector = _Collector(root, target)
    collector.visit(entrypoint)
    _check_expansion(entrypoint, collector.children, collector.sizes, collector.repetitions)
    return tuple(collector.names), tuple(collector.edges)


def _check_expansion(
    entrypoint: str,
    children: dict[str, tuple[str, ...]],
    sizes: dict[str, int],
    repetitions: dict[str, int],
) -> None:
    pending = [entrypoint]
    expanded_files = 0
    expanded_size = 0
    expanded_repetitions = 0
    while pending:
        name = pending.pop()
        expanded_files += 1
        expanded_size += sizes[name]
        expanded_repetitions += repetitions[name]
        if expanded_repetitions > 200_000:
            raise invalid("Repeated input values exceed 200,000 entries.")
        if expanded_files > MAX_EXPANDED_FILES or expanded_size > MAX_CHARACTERS:
            raise invalid("Expanded includes exceed 256 file visits or 2,000,000 characters.")
        pending.extend(children[name])
