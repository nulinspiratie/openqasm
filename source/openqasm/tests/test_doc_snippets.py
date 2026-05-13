"""Round-trip validation for OpenQASM code snippets embedded in the spec docs.

Each snippet is extracted from source/language/*.rst, parsed to an AST, printed
back to text, and re-parsed. Snippets that cannot stand alone (pseudocode,
intentionally invalid examples, fragments requiring prior context) should be
annotated with a ``.. # parse-test: skip`` RST comment immediately before the
``.. code-block::`` directive or the paragraph that ends with ``::``.

The ANTLR-generated files in ``openqasm3/_antlr/_4_13/`` are git-ignored and
must be regenerated from the grammar before this test suite will import
successfully.  See ``.github/workflows/build-ast.yml`` for the canonical
command (Java + ``antlr-4.13.0-complete.jar`` on ``source/grammar/*.g4``).
"""

import pathlib
import re
import textwrap
from typing import List, Tuple

import pytest

import openqasm3

_LANGUAGE_DIR = pathlib.Path(__file__).parents[2] / "language"
_SKIP_MARKER = ".. # parse-test: skip"


def _body_from_lines(lines: List[str], start: int, base_indent: int) -> Tuple[str, int]:
    """Collect an indented block starting at *start* whose lines have indent > *base_indent*.

    *base_indent* is the indentation of the containing directive or `::` line, not the
    first content line.  Blank lines inside the block are preserved; the block ends at the
    first non-blank line with indent <= base_indent.

    Returns (dedented_body, next_line_index).
    """
    body_lines: List[str] = []
    i = start
    while i < len(lines):
        raw = lines[i]
        stripped = raw.rstrip()
        if stripped == "":
            body_lines.append("")
            i += 1
            continue
        indent = len(raw) - len(raw.lstrip())
        if indent <= base_indent:
            break
        body_lines.append(stripped)
        i += 1

    # Strip trailing blank lines
    while body_lines and body_lines[-1] == "":
        body_lines.pop()

    body = textwrap.dedent("\n".join(body_lines)).strip()
    return body, i


def _extract_snippets(rst_path: pathlib.Path) -> List[Tuple[int, str]]:
    """Return list of (1-based line number, snippet text) from an RST file."""
    snippets: List[Tuple[int, str]] = []
    lines = rst_path.read_text().splitlines()
    n = len(lines)
    skip_next = False
    i = 0

    while i < n:
        raw = lines[i]
        stripped = raw.strip()

        # Skip marker — applies to the next code block found
        if re.match(r"^\s*\.\.\s+#\s+parse-test:\s+skip\s*$", raw):
            skip_next = True
            i += 1
            continue

        # ── code-block directive ──────────────────────────────────────────────
        m = re.match(r"^(\s*)\.\. code-block::\s*(\S*)", raw)
        if m:
            directive_indent = len(m.group(1))
            language = m.group(2).lower()
            block_line = i + 1  # 1-based

            # Skip blocks that are explicitly in a non-OpenQASM language.
            # (The default, "qasm3", and "" are all treated as OpenQASM.)
            _SKIP_LANGUAGES = {"python", "openpulse"}
            if language in _SKIP_LANGUAGES:
                i += 1
                skip_next = False
                continue

            i += 1
            # Skip directive options (:linenos:, :class:, etc.) and blank lines
            while i < n:
                opt = lines[i].strip()
                if opt == "" or re.match(r"^\s+:", lines[i]):
                    i += 1
                else:
                    break

            # Determine content indentation from first non-blank content line
            if i < n and lines[i].strip():
                content_indent = len(lines[i]) - len(lines[i].lstrip())
                if content_indent > directive_indent:
                    body, i = _body_from_lines(lines, i, directive_indent)
                    if body:
                        if skip_next:
                            skip_next = False
                        else:
                            snippets.append((block_line, body))
                    else:
                        skip_next = False
                    continue

            skip_next = False
            continue

        # ── RST literal block (paragraph ending with ::) ─────────────────────
        # Only match lines that end with "::" but are NOT directives themselves.
        if (
            raw.rstrip().endswith("::")
            and not stripped.startswith("..")
            and stripped != "::"
        ):
            literal_indent = len(raw) - len(raw.lstrip())
            block_line = i + 1
            i += 1

            # Skip blank lines between paragraph and content
            while i < n and lines[i].strip() == "":
                i += 1

            if i < n and lines[i].strip():
                content_indent = len(lines[i]) - len(lines[i].lstrip())
                if content_indent > 0:
                    body, i = _body_from_lines(lines, i, literal_indent)
                    if body:
                        if skip_next:
                            skip_next = False
                        else:
                            snippets.append((block_line, body))
                    else:
                        skip_next = False
                    continue

            skip_next = False
            continue

        i += 1

    return snippets


def _collect_params() -> List[pytest.param]:
    params = []
    for rst_file in sorted(_LANGUAGE_DIR.glob("*.rst")):
        for line_num, snippet in _extract_snippets(rst_file):
            test_id = f"{rst_file.stem}::L{line_num}"
            params.append(pytest.param(snippet, id=test_id))
    return params


@pytest.mark.parametrize("snippet", _collect_params())
def test_doc_snippet_round_trip(snippet: str) -> None:
    """Parse snippet → AST, print → text, re-parse.  Both parses must succeed."""
    ast1 = openqasm3.parse(snippet)
    reprinted = openqasm3.dumps(ast1)
    openqasm3.parse(reprinted)
