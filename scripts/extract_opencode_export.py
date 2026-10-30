#!/usr/bin/env python3
"""Convert a native OpenCode session export into a filtered conversation view.

Supported input
---------------
The JSON file written by ``opencode session export SESSION_ID`` of OpenCode
v2.2.1.  Such an export is an object with an ``info`` object and a
``messages`` array.  The array order is authoritative: message identifiers are
never sorted and never used to restore the order.

Only the visible conversation text is kept:

* a ``user`` message contributes its ``text`` field,
* an ``assistant`` message contributes its direct ``text`` content blocks,
  joined with a blank line ("\\n\\n") between two blocks.

Text is copied verbatim.  Nothing is unescaped, repaired, re-encoded or
trimmed, so Unicode, HTML entities, indentation and embedded newlines stay
exactly as the export wrote them.

Everything else is dropped and only counted: tool calls with their inputs and
outputs, reasoning, and the messages of the types "agent-switched",
"model-switched", "location-switched", "synthetic", "system", "skill",
"shell", "compaction" and "idle".  The names, paths and contents of user
attachments are not copied either, only the number of attachments is counted.

An input that is not a supported export is rejected with a short error.  The
error names the position of the offending record and the kinds that are
supported.  It never repeats a value that came out of the file, so a rejected
export cannot leak its own content through the error message.

The result is a filtered conversation view.  It is not a full archive and it
is not secret redaction: a secret that was already part of the visible text
stays in the text.  An export that was written with the native ``--sanitize``
option keeps its placeholders; their original text cannot be recovered.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


#: Extraction succeeded.
EXIT_OK = 0

#: The input file is missing, unreadable, not valid UTF-8/JSON, or not a
#: supported OpenCode session export.
EXIT_INPUT_ERROR = 3

#: An output file could not be written, already exists, or aliases another
#: path.
EXIT_OUTPUT_ERROR = 4


#: Message types that carry the visible conversation.
CONVERSATION_TYPES = ("user", "assistant")

#: Message types of OpenCode v2.2.1 that are not conversation text.  They are
#: omitted from the output and only counted.
IGNORED_MESSAGE_TYPES = (
    "agent-switched",
    "model-switched",
    "location-switched",
    "synthetic",
    "system",
    "skill",
    "shell",
    "compaction",
    "idle",
)

#: Assistant content block types of OpenCode v2.2.1.  Only "text" is visible
#: conversation text.
ASSISTANT_BLOCK_TYPES = ("text", "reasoning", "tool")

#: Assistant content block types that are not visible conversation text.
NON_VISIBLE_ASSISTANT_BLOCK_TYPES = ("reasoning", "tool")

#: Separator between two visible assistant text blocks of the same message.
ASSISTANT_BLOCK_SEPARATOR = "\n\n"

#: Header of the Markdown output.
MARKDOWN_TITLE = "# OpenCode Session Export - Filtered Conversation"

#: Notice that is part of every Markdown output.
MARKDOWN_NOTICE = (
    "Filtered view of a native OpenCode session export. It is not a full archive\n"
    "and it is not secret redaction: secrets that were already part of the\n"
    "visible text stay in the text."
)

#: Notice that is part of every normalized JSON output.
JSON_NOTE = (
    "Filtered conversation view of an OpenCode session export. "
    "Not a full archive and not secret redaction."
)


class ExportError(RuntimeError):
    """The input is not a supported OpenCode session export."""

    exit_code = EXIT_INPUT_ERROR


class OutputError(ExportError):
    """An output file cannot be written."""

    exit_code = EXIT_OUTPUT_ERROR


def load_export(path: Path) -> list[Any]:
    """Read an export file and return its validated ``messages`` array.

    The file is read as UTF-8, with or without a byte order mark.  Anything
    that is not an object with an ``info`` object and a ``messages`` array is
    rejected.
    """
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise ExportError(f"input file does not exist: {path}") from exc
    except IsADirectoryError as exc:
        raise ExportError(f"input path is a directory, not a file: {path}") from exc
    except OSError as exc:
        raise ExportError(f"cannot read input file: {path}") from exc

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ExportError(
            f"input file is not valid UTF-8 (a UTF-8 byte order mark is accepted): {path}"
        ) from exc

    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ExportError(
            f"input file is not valid JSON (line {exc.lineno}, column {exc.colno}): {path}"
        ) from exc

    if not isinstance(document, dict):
        raise ExportError(
            "unsupported export: the root must have an 'info' object and a "
            "'messages' array"
        )
    if "info" not in document:
        raise ExportError(
            "unsupported export: the root must have an 'info' object and a "
            "'messages' array"
        )
    if not isinstance(document["info"], dict):
        raise ExportError("unsupported export: 'info' must be an object")
    messages = document.get("messages")
    if not isinstance(messages, list):
        raise ExportError("unsupported export: 'messages' must be an array")
    return messages


def _message_type(message: dict[str, Any], index: int) -> str:
    """Return the type of a message, rejecting unknown and legacy shapes."""
    if "type" not in message:
        if "parts" in message or "info" in message:
            raise ExportError(
                f"message {index}: legacy export shape (info/parts) is not supported; "
                "use the native OpenCode v2 session export"
            )
        raise ExportError(f"message {index}: missing 'type'")
    message_type = message["type"]
    if not isinstance(message_type, str):
        raise ExportError(f"message {index}: 'type' must be a string")
    return message_type


def _user_text(message: dict[str, Any], index: int) -> tuple[str, int]:
    """Return the visible text of a user message and its attachment count."""
    text = message.get("text")
    if not isinstance(text, str):
        raise ExportError(f"message {index}: a user message needs a 'text' string")
    files = message.get("files")
    if files is None:
        return text, 0
    if not isinstance(files, list):
        raise ExportError(f"message {index}: 'files' must be an array")
    return text, len(files)


def _assistant_text(message: dict[str, Any], index: int) -> tuple[str, dict[str, int]]:
    """Return the visible text of an assistant message and its omitted blocks.

    Only direct ``text`` blocks are visible.  The contents of ``reasoning``
    and ``tool`` blocks are never read, so text that a tool returned stays
    inside the tool block.
    """
    content = message.get("content")
    if not isinstance(content, list):
        raise ExportError(f"message {index}: an assistant message needs a 'content' array")

    visible: list[str] = []
    omitted = {name: 0 for name in NON_VISIBLE_ASSISTANT_BLOCK_TYPES}
    for block in content:
        if not isinstance(block, dict):
            raise ExportError(
                f"message {index}: an assistant content block must be an object"
            )
        block_type = block.get("type")
        if not isinstance(block_type, str):
            raise ExportError(
                f"message {index}: an assistant content block needs a 'type' string"
            )
        if block_type not in ASSISTANT_BLOCK_TYPES:
            raise ExportError(
                f"message {index}: unsupported assistant content block type; "
                f"supported types are: {', '.join(ASSISTANT_BLOCK_TYPES)}"
            )
        if block_type == "text":
            block_text = block.get("text")
            if not isinstance(block_text, str):
                raise ExportError(
                    f"message {index}: an assistant text block needs a 'text' string"
                )
            if block_text.strip():
                visible.append(block_text)
        else:
            omitted[block_type] += 1
    return ASSISTANT_BLOCK_SEPARATOR.join(visible), omitted


def extract_conversation(messages: list[Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Split an export into visible conversation text and a summary.

    The returned messages keep the position they had in the exported array as
    ``source_index``.  The summary counts what was left out.
    """
    retained: list[dict[str, Any]] = []
    ignored_types = {name: 0 for name in IGNORED_MESSAGE_TYPES}
    omitted_blocks = {name: 0 for name in NON_VISIBLE_ASSISTANT_BLOCK_TYPES}
    omitted_messages = 0
    attachments = 0

    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            raise ExportError(f"message {index}: must be an object")
        message_type = _message_type(message, index)

        if message_type == "user":
            text, file_count = _user_text(message, index)
            attachments += file_count
            if text.strip():
                retained.append({"source_index": index, "role": "user", "text": text})
            else:
                omitted_messages += 1
        elif message_type == "assistant":
            text, block_counts = _assistant_text(message, index)
            for name, count in block_counts.items():
                omitted_blocks[name] += count
            if text:
                retained.append(
                    {"source_index": index, "role": "assistant", "text": text}
                )
            else:
                omitted_messages += 1
        elif message_type in ignored_types:
            ignored_types[message_type] += 1
        else:
            raise ExportError(
                f"message {index}: unsupported message type; supported types are: "
                + ", ".join(CONVERSATION_TYPES + IGNORED_MESSAGE_TYPES)
            )

    summary = {
        "source_messages": len(messages),
        "retained_messages": len(retained),
        "omitted_messages": omitted_messages,
        "ignored_messages": sum(ignored_types.values()),
        "ignored_message_types": {
            name: count for name, count in ignored_types.items() if count
        },
        "omitted_assistant_blocks": {
            name: count for name, count in omitted_blocks.items() if count
        },
        "user_attachments": attachments,
    }
    return retained, summary


def _format_counts(counts: dict[str, int], order: tuple[str, ...]) -> str:
    """Format counters in a fixed order, so the output stays reproducible."""
    parts = [f"{name} {counts[name]}" for name in order if counts.get(name)]
    return ", ".join(parts) if parts else "none"


def render_markdown(retained: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    """Render the filtered conversation as Markdown."""
    lines = [
        MARKDOWN_TITLE,
        "",
        MARKDOWN_NOTICE,
        "",
        "## Summary",
        "",
        "- Input kind: native OpenCode session export (JSON)",
        f"- Source messages: {summary['source_messages']}",
        f"- Retained messages: {summary['retained_messages']}",
        f"- Omitted messages without visible text: {summary['omitted_messages']}",
        "- Omitted message types: "
        + _format_counts(summary["ignored_message_types"], IGNORED_MESSAGE_TYPES),
        "- Omitted assistant blocks: "
        + _format_counts(
            summary["omitted_assistant_blocks"], NON_VISIBLE_ASSISTANT_BLOCK_TYPES
        ),
        "- User attachments: "
        f"{summary['user_attachments']} (names, paths and contents are not included)",
        "",
        "## Conversation",
        "",
    ]
    if not retained:
        lines.extend(["- (no visible conversation text)", ""])
        return "\n".join(lines)

    for number, message in enumerate(retained, start=1):
        role = "User" if message["role"] == "user" else "Assistant"
        lines.append(f"### {number}. {role}")
        lines.append("")
        lines.append(message["text"])
        lines.append("")
    return "\n".join(lines)


def render_json(retained: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    """Render the filtered conversation as normalized JSON."""
    payload = {
        "format": "opencode-session-export-conversation",
        "version": 1,
        "note": JSON_NOTE,
        "summary": summary,
        "messages": retained,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _path_key(path: Path) -> str:
    """Return a comparable key for a path, resolving links when possible."""
    try:
        return os.path.normcase(str(path.resolve()))
    except OSError:
        return os.path.normcase(os.path.abspath(str(path)))


def _same_path(first: Path, second: Path) -> bool:
    """Return whether two paths point at the same file."""
    if _path_key(first) == _path_key(second):
        return True
    try:
        return os.path.samefile(first, second)
    except OSError:
        return False


def check_output_paths(
    input_path: Path, markdown_path: Path | None, json_path: Path | None
) -> None:
    """Reject output paths that exist or that alias the input or each other."""
    for path in (markdown_path, json_path):
        if path is None:
            continue
        if path.exists():
            if path.is_dir():
                raise OutputError(f"output path is a directory, not a file: {path}")
            raise OutputError(f"output file already exists: {path}")
        if _same_path(path, input_path):
            raise OutputError(f"output path must not be the input file: {path}")
    if markdown_path is not None and json_path is not None:
        if _same_path(markdown_path, json_path):
            raise OutputError(
                f"--out and --json-out must not be the same file: {markdown_path}"
            )


def _write_exclusive(path: Path, text: str) -> None:
    """Create a file that must not exist yet, and never overwrite anything."""
    try:
        with open(path, "x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    except FileExistsError as exc:
        raise OutputError(f"output file already exists: {path}") from exc
    except OSError as exc:
        raise OutputError(f"cannot write output file: {path}") from exc


def _write_stdout(text: str) -> None:
    """Write UTF-8 to stdout, independent of the console code page."""
    data = text.encode("utf-8")
    buffer = getattr(sys.stdout, "buffer", None)
    try:
        if buffer is not None:
            buffer.write(data)
            buffer.flush()
        else:
            sys.stdout.write(text)
            sys.stdout.flush()
    except BrokenPipeError as exc:
        raise OutputError("cannot write to stdout: the output stream was closed") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Convert a native OpenCode session export (JSON) into a filtered "
            "conversation view."
        ),
    )
    parser.add_argument("json_file", help="path to a native OpenCode session export")
    parser.add_argument("--out", help="write the Markdown transcript to this path")
    parser.add_argument(
        "--json-out", help="write the normalized conversation JSON to this path"
    )
    args = parser.parse_args(argv)

    input_path = Path(args.json_file)
    markdown_path = Path(args.out) if args.out else None
    json_path = Path(args.json_out) if args.json_out else None

    try:
        if not input_path.exists():
            raise ExportError(f"input file does not exist: {input_path}")
        if not input_path.is_file():
            raise ExportError(f"input path is not a file: {input_path}")

        messages = load_export(input_path)
        retained, summary = extract_conversation(messages)
        markdown = render_markdown(retained, summary)
        normalized = render_json(retained, summary)

        check_output_paths(input_path, markdown_path, json_path)
    except ExportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code

    try:
        if markdown_path is not None:
            _write_exclusive(markdown_path, markdown)
        else:
            _write_stdout(markdown)
        if json_path is not None:
            _write_exclusive(json_path, normalized)
    except ExportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code

    user_count = sum(1 for message in retained if message["role"] == "user")
    assistant_count = sum(1 for message in retained if message["role"] == "assistant")
    print(
        "messages={0} user={1} assistant={2} omitted={3} ignored={4} attachments={5}".format(
            len(retained),
            user_count,
            assistant_count,
            summary["omitted_messages"],
            summary["ignored_messages"],
            summary["user_attachments"],
        ),
        file=sys.stderr,
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
