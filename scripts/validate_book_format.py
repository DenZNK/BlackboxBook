#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BOOK_ROOT = REPO_ROOT / "book"

BOOK_FILENAME_PATTERN = re.compile(r"^\d{2}_.+\.md$")
NUMBERED_SECTION_PATTERN = re.compile(r"^##\s+(\d+)\.(\d+)\.")
TABLE_SEPARATOR_CELL_PATTERN = re.compile(r":?-{3,}:?")
LATEX_BOOK_MACRO_PATTERN = re.compile(r"\\Book[A-Za-z]+")
REDUNDANT_TABLE_SYMBOL_PATTERN = re.compile(r"^[ \t]*[✓✗⚠↻★][ \t]+\S")

FORBIDDEN_TEXT_SNIPPETS = {
    "✅": "Use `✓` instead of `✅`.",
    "❌": "Use `✗` instead of `❌`.",
    "⚠️": "Use `⚠` instead of `⚠️`.",
    "❗": "Use `⚠` or plain text instead of `❗`.",
    "🔄": "Use `↻` instead of `🔄`.",
    "↺": "Use `↻` instead of `↺`.",
    "⭐": "Use `★` instead of `⭐`.",
    " ": "Use a normal space instead of a thin space (U+2009).",
    "ₙ": "Use `_n` instead of subscript `ₙ`.",
}

REQUIRED_END_BLOCKS = (
    "## Источники",
    "**Навигация:**",
)

RECOMMENDED_END_BLOCKS = (
    "## Практический вывод",
)


@dataclass(frozen=True)
class Issue:
    severity: str
    path: Path
    line: int
    code: str
    message: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate BlackboxBook Markdown formatting rules.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=[str(DEFAULT_BOOK_ROOT)],
        help="Markdown files or directories to validate. Defaults to `book/`.",
    )
    return parser.parse_args()


def discover_markdown_files(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()

    for raw_path in paths:
        path = Path(raw_path).expanduser().resolve()
        if path.is_file():
            if path.suffix.lower() == ".md" and path not in seen:
                files.append(path)
                seen.add(path)
            continue

        if path.is_dir():
            for candidate in sorted(path.rglob("*.md")):
                if candidate not in seen and ".git" not in candidate.parts:
                    files.append(candidate)
                    seen.add(candidate)

    return files


def relative_path(path: Path) -> Path:
    try:
        return path.relative_to(REPO_ROOT)
    except ValueError:
        return path


def is_pipe_table_separator(line: str) -> bool:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return False
    cells = [cell.strip() for cell in stripped[1:-1].split("|")]
    return bool(cells) and all(TABLE_SEPARATOR_CELL_PATTERN.fullmatch(cell.replace(" ", "")) for cell in cells)


def validate_file(path: Path) -> list[Issue]:
    issues: list[Issue] = []
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    rel_path = relative_path(path)

    if path.parent == DEFAULT_BOOK_ROOT and not BOOK_FILENAME_PATTERN.fullmatch(path.name):
        issues.append(
            Issue("error", rel_path, 1, "filename", "Chapter file name must use `NN_snake_case.md` format."),
        )

    first_nonempty_line = next(((index + 1, line) for index, line in enumerate(lines) if line.strip()), None)
    if not first_nonempty_line:
        issues.append(Issue("error", rel_path, 1, "empty-file", "Markdown file is empty."))
        return issues

    first_line_no, first_line = first_nonempty_line
    if not first_line.startswith("# "):
        issues.append(
            Issue("error", rel_path, first_line_no, "top-heading", "First non-empty line must be a level-1 heading (`# ...`)."),
        )

    found_positions: list[int] = []
    for block in REQUIRED_END_BLOCKS:
        position = next((index + 1 for index, line in enumerate(lines) if line.strip() == block), None)
        if position is None:
            issues.append(Issue("error", rel_path, 1, "required-block", f"Missing required block `{block}`."))
            continue
        found_positions.append(position)

    if len(found_positions) == len(REQUIRED_END_BLOCKS) and found_positions != sorted(found_positions):
        issues.append(
            Issue("error", rel_path, found_positions[0], "block-order", "`Источники` must appear before `Навигация`."),
        )

    recommended_positions: list[int] = []
    for block in RECOMMENDED_END_BLOCKS:
        position = next((index + 1 for index, line in enumerate(lines) if line.strip() == block), None)
        if position is None:
            issues.append(
                Issue(
                    "warning",
                    rel_path,
                    1,
                    "recommended-block",
                    f"Recommended block `{block}` is missing.",
                )
            )
            continue
        recommended_positions.append(position)

    order_positions = [*recommended_positions, *found_positions]
    if len(order_positions) == len(RECOMMENDED_END_BLOCKS) + len(REQUIRED_END_BLOCKS) and order_positions != sorted(order_positions):
        issues.append(
            Issue("error", rel_path, order_positions[0], "block-order", "`Практический вывод`, `Источники`, and `Навигация` must stay in this order."),
        )

    chapter_prefix = None
    if path.parent == DEFAULT_BOOK_ROOT:
        chapter_prefix = int(path.name[:2])

    for index, line in enumerate(lines, start=1):
        for forbidden, message in FORBIDDEN_TEXT_SNIPPETS.items():
            if forbidden in line:
                issues.append(Issue("error", rel_path, index, "forbidden-symbol", message))

        if LATEX_BOOK_MACRO_PATTERN.search(line):
            issues.append(
                Issue("error", rel_path, index, "latex-macro", "Do not use internal `\\Book...` TeX macros in manuscript Markdown."),
            )

        match = NUMBERED_SECTION_PATTERN.match(line)
        if match and chapter_prefix is not None and int(match.group(1)) != chapter_prefix:
            issues.append(
                Issue(
                    "error",
                    rel_path,
                    index,
                    "section-number",
                    f"Section numbering should start with `{chapter_prefix}.x` in this chapter.",
                )
            )

        if line.strip().startswith("|") and line.strip().endswith("|") and not is_pipe_table_separator(line):
            cells = [cell.strip() for cell in line.strip()[1:-1].split("|")]
            for cell in cells:
                if REDUNDANT_TABLE_SYMBOL_PATTERN.match(cell):
                    issues.append(
                        Issue(
                            "error",
                            rel_path,
                            index,
                            "table-symbol",
                            "Remove redundant leading status symbols from table cells when the text already conveys the meaning.",
                        )
                    )
                    break

    return issues


def print_issues(issues: list[Issue]) -> None:
    for issue in issues:
        print(f"{issue.severity.upper():7} {issue.path}:{issue.line} [{issue.code}] {issue.message}")


def main() -> int:
    args = parse_args()
    files = discover_markdown_files(args.paths)
    if not files:
        print("No Markdown files found.", file=sys.stderr)
        return 1

    all_issues: list[Issue] = []
    for path in files:
        all_issues.extend(validate_file(path))

    if all_issues:
        print_issues(sorted(all_issues, key=lambda item: (str(item.path), item.line, item.code)))
        error_count = sum(issue.severity == "error" for issue in all_issues)
        warning_count = len(all_issues) - error_count
        if error_count:
            print(f"\nValidation failed: {error_count} error(s), {warning_count} warning(s) across {len(files)} file(s).")
        else:
            print(f"\nValidation completed with warnings: {warning_count} warning(s) across {len(files)} file(s).")
        return 1 if error_count else 0

    print(f"Validation passed: {len(files)} file(s) checked, no formatting issues found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
