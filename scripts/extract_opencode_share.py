#!/usr/bin/env python3
"""Extract the visible transcript from an OpenCode share page."""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
import urllib.request
import urllib.error
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


class ShareExtractError(RuntimeError):
    exit_code = 1


class NetworkFetchError(ShareExtractError):
    exit_code = 2


class SessionDataMissingError(ShareExtractError):
    exit_code = 3


class EmptyTranscriptError(ShareExtractError):
    exit_code = 4


def normalize_source(source: str) -> str:
    match = re.match(r"^https?://(?:www\.)?opencode\.ai/s/([^/?#]+)", source, re.I)
    if match:
        return f"https://opncd.ai/share/{match.group(1)}"
    return source


def read_source(source: str) -> tuple[str, str]:
    source = normalize_source(source)
    if re.match(r"^https?://", source, re.I):
        req = urllib.request.Request(
            source,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/120 Safari/537.36"
                )
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                data = response.read().decode(charset, errors="replace")
            return data, source
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise NetworkFetchError(f"failed to fetch URL: {source}") from exc

    path = Path(source)
    try:
        return path.read_text(encoding="utf-8", errors="replace"), str(path.resolve())
    except OSError as exc:
        raise NetworkFetchError(f"failed to read file: {path}") from exc


def decode_js_string(raw: str) -> str:
    try:
        return json.loads(f'"{raw}"')
    except Exception:
        return (
            raw.replace(r"\n", "\n")
            .replace(r"\r", "\r")
            .replace(r"\t", "\t")
            .replace(r"\"", '"')
            .replace(r"\\", "\\")
        )


def fix_mojibake(text: str) -> str:
    """Repair UTF-8 bytes that were decoded as Latin-1, without losing text.

    The repair is attempted on the whole string and only when it is lossless:
    the text must be encodable as Latin-1 and the resulting bytes must decode
    as UTF-8. If either step fails, the original text is returned unchanged
    instead of dropping the characters that could not be re-encoded.
    """
    if not re.search(r"[\u00c0-\u00ff]", text):
        return text
    try:
        fixed = text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    if re.search(r"[\u4e00-\u9fff]", fixed) and fixed.count("\ufffd") <= text.count("\ufffd"):
        return fixed
    return text


def clean_text(text: str) -> str:
    text = html.unescape(text)
    text = fix_mojibake(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.strip()


def js_field(obj: str, name: str) -> str | None:
    match = re.search(rf'{re.escape(name)}:"((?:\\.|[^"\\])*)"', obj)
    if not match:
        return None
    return clean_text(decode_js_string(match.group(1)))


def js_number(obj: str, name: str) -> int | float | None:
    match = re.search(rf"{re.escape(name)}:([0-9]+(?:\.[0-9]+)?)", obj)
    if not match:
        return None
    value = match.group(1)
    return float(value) if "." in value else int(value)


def ms_to_iso(value: int | float | None) -> str | None:
    if value is None:
        return None
    try:
        return dt.datetime.fromtimestamp(float(value) / 1000, tz=dt.timezone.utc).isoformat()
    except (OSError, OverflowError, ValueError):
        return None


def compact_dict(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value not in (None, {}, [])}


def extract_metadata(page: str, source: str) -> dict[str, Any]:
    session_match = re.search(r"session:\$R\[\d+\]=\[\$R\[\d+\]=\{([\s\S]{0,8000}?)\}\]", page)
    session_obj = session_match.group(1) if session_match else ""

    model_match = re.search(r"model:\$R\[\d+\]=\{([\s\S]{0,800}?)\}", session_obj)
    model_obj = model_match.group(1) if model_match else ""

    tokens_match = re.search(r"tokens:\$R\[\d+\]=\{([\s\S]{0,800}?)\}", session_obj)
    tokens_obj = tokens_match.group(1) if tokens_match else ""

    time_match = re.search(r"time:\$R\[\d+\]=\{([\s\S]{0,400}?)\}", session_obj)
    time_obj = time_match.group(1) if time_match else ""
    created_ms = js_number(time_obj, "created")
    updated_ms = js_number(time_obj, "updated")

    return compact_dict(
        {
            "source": source,
            "share_id": js_field(page, "shareID"),
            "session_id": js_field(session_obj, "id"),
            "title": js_field(session_obj, "title"),
            "directory": js_field(session_obj, "directory"),
            "agent": js_field(session_obj, "agent"),
            "version": js_field(session_obj, "version"),
            "model": compact_dict(
                {
                    "id": js_field(model_obj, "id"),
                    "provider": js_field(model_obj, "providerID"),
                    "variant": js_field(model_obj, "variant"),
                }
            ),
            "cost": js_number(session_obj, "cost"),
            "tokens": compact_dict(
                {
                    "input": js_number(tokens_obj, "input"),
                    "output": js_number(tokens_obj, "output"),
                    "reasoning": js_number(tokens_obj, "reasoning"),
                }
            ),
            "time": compact_dict(
                {
                    "created_ms": created_ms,
                    "updated_ms": updated_ms,
                    "created": ms_to_iso(created_ms),
                    "updated": ms_to_iso(updated_ms),
                }
            ),
        }
    )


def extract_roles(page: str) -> dict[str, str]:
    roles: dict[str, str] = {}
    pattern = re.compile(
        r"\$R\[\d+\]=\{[\s\S]{0,16000}?role:\"(user|assistant)\""
        r"[\s\S]{0,16000}?id:\"(msg_[^\"]+)\"",
        re.M,
    )
    for match in pattern.finditer(page):
        roles[match.group(2)] = match.group(1)
    return roles


#: A double quoted JavaScript string, including its backslash escapes.
_JS_STRING_RE = re.compile(r'"(?:\\.|[^"\\])*"', re.S)

#: Characters that can change the nesting level of a serialized array.
_JS_STRUCT_RE = re.compile(r'["\[\]{}]')

#: The start of a string, or the reference to a message parts array.
_SCAN_EVENT_RE = re.compile(r'"|msg_(?P<suffix>[A-Za-z0-9]+):\$R\[\d+\]=\[')

#: A visible text part inside a parts array.
_TEXT_PART_RE = re.compile(r'type:"text",text:"((?:\\.|[^"\\])*)"')

#: The closing bracket that belongs to each opening bracket.
_BRACKET_PAIRS = {"[": "]", "{": "}"}

#: The characters that may precede a message key.
_KEY_CONTEXTS = ("", "{", ",")


#: The characters that may precede the markup of a saved page.
_MARKUP_PADDING = "\ufeff \t\r\n\f\v"


class _ScriptCollector(HTMLParser):
    """Collect the contents of the script elements of a page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.scripts: list[str] = []
        self._current: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and self._current is None:
            self._current = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._current is not None:
            self.scripts.append("".join(self._current))
            self._current = None

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            self._current.append(data)


def _is_markup_document(page: str) -> bool:
    """Return whether the input starts like a markup document.

    A saved page may start with whitespace or a UTF-8 BOM before its markup,
    so both are skipped before the check. Input that does not start like
    markup is a raw serialized fragment, even when its quoted text contains
    script tags.
    """
    return page.lstrip(_MARKUP_PADDING).startswith("<")


def _script_blocks(page: str) -> list[str]:
    """Return the contents of the script elements of the page, in page order."""
    collector = _ScriptCollector()
    collector.feed(page)
    collector.close()
    return collector.scripts


def _payload_fragments(page: str) -> list[str]:
    """Return the parts of the page that can hold the serialized share data.

    A markup document is read through its script elements, because the
    JavaScript of a saved share page lives there. Every script element stays a
    separate fragment, so an unrelated script cannot swallow the payload of
    another one, and text outside the script elements is never read as
    JavaScript. A markup document without script elements has no script data,
    so it is read as a raw fragment as well.

    Input that does not start like markup is a raw serialized fragment and is
    read as it is, even when its quoted text contains script tags.
    """
    if not _is_markup_document(page):
        return [page]
    scripts = _script_blocks(page)
    if scripts:
        return scripts
    return [page]


def _skip_js_string(fragment: str, index: int) -> int | None:
    """Return the index just after the string that starts at ``index``.

    ``None`` is returned when the string is never closed.
    """
    match = _JS_STRING_RE.match(fragment, index)
    if match is None:
        return None
    return match.end()


def _scan_array_end(fragment: str, open_index: int) -> int | None:
    """Return the index of the bracket that closes the array at ``open_index``.

    Nested brackets, nested references and quoted strings are respected, so a
    bracket inside a string value never ends the array early. ``None`` is
    returned when the array is never closed.
    """
    stack = [fragment[open_index]]
    position = open_index + 1
    while True:
        token = _JS_STRUCT_RE.search(fragment, position)
        if token is None:
            return None
        char = token.group(0)
        if char == '"':
            end = _skip_js_string(fragment, token.start())
            if end is None:
                return None
            position = end
            continue
        position = token.end()
        if char in _BRACKET_PAIRS:
            stack.append(char)
            continue
        opener = stack.pop()
        if _BRACKET_PAIRS[opener] != char:
            return None
        if not stack:
            return token.start()


def _find_parts_arrays(fragment: str) -> list[tuple[str, int, int]]:
    """Locate the parts array of every message in a serialized fragment.

    The fragment is scanned as the serialized payload it is: double quoted
    strings are skipped as a whole, so their content is never read as
    structure and a message key inside a quoted string is not a message.

    Every result is a ``(message id, first index inside the array, index of
    the closing bracket)`` triple. Only arrays whose end can be determined are
    reported: an array that is never closed must not produce a partial text
    block, and the parser must not borrow the text of a later message.
    """
    found: list[tuple[str, int, int]] = []
    position = 0
    length = len(fragment)
    while position < length:
        event = _SCAN_EVENT_RE.search(fragment, position)
        if event is None:
            break
        if event.group(0) == '"':
            end = _skip_js_string(fragment, event.start())
            if end is None:
                break
            position = end
            continue
        start = event.start()
        previous = fragment[start - 1] if start else ""
        if previous not in _KEY_CONTEXTS:
            # Not written as an object key, so not a message key.
            position = event.end()
            continue
        open_index = event.end() - 1
        close_index = _scan_array_end(fragment, open_index)
        if close_index is None:
            break
        found.append(("msg_" + event.group("suffix"), open_index + 1, close_index))
        position = close_index + 1
    return found


def extract_text_parts(page: str) -> dict[str, str]:
    """Read the visible text of every message from its own parts array.

    The end of a parts array is found by scanning the serialized data of the
    page, so the text of a message is read from that array only. It is never
    cut off at a fixed character count, and data that follows the array is
    not collected.
    """
    parts: dict[str, str] = {}
    for fragment in _payload_fragments(page):
        for msg_id, body_start, body_end in _find_parts_arrays(fragment):
            texts: list[str] = []
            for text_match in _TEXT_PART_RE.finditer(fragment[body_start:body_end]):
                value = clean_text(decode_js_string(text_match.group(1)))
                if value:
                    texts.append(value)
            if texts:
                parts[msg_id] = "\n".join(texts)
    return parts


def extract_message_order(page: str, roles: dict[str, str]) -> list[str]:
    order: list[str] = []
    for match in re.finditer(r'id:"(msg_[^"]+)"', page):
        msg_id = match.group(1)
        if msg_id in roles and msg_id not in order:
            order.append(msg_id)
    return order


def parse_session(page: str) -> list[dict[str, Any]]:
    if "getShareData" not in page and "sessionID" not in page:
        raise SessionDataMissingError(
            "no OpenCode share data found; use an opncd.ai/share/<id> URL or a saved share HTML file"
        )

    roles = extract_roles(page)
    parts = extract_text_parts(page)
    order = extract_message_order(page, roles)

    messages: list[dict[str, Any]] = []
    for msg_id in order:
        text = parts.get(msg_id)
        if text:
            messages.append({"id": msg_id, "role": roles[msg_id], "text": text})
    if not messages:
        raise EmptyTranscriptError("OpenCode share data was found, but no visible transcript text was extracted")
    return messages


def to_markdown(messages: list[dict[str, Any]], metadata: dict[str, Any]) -> str:
    lines = [
        "# OpenCode Share Session - Clean Transcript",
        "",
        "## Metadata",
        "",
        f"Source: {metadata.get('source', '')}",
        f"Messages: {len(messages)}",
    ]
    for label, key in [
        ("Share ID", "share_id"),
        ("Session ID", "session_id"),
        ("Title", "title"),
        ("Directory", "directory"),
        ("Agent", "agent"),
        ("Version", "version"),
        ("Cost", "cost"),
    ]:
        if key in metadata:
            lines.append(f"{label}: {metadata[key]}")

    model = metadata.get("model", {})
    if model:
        model_text = " / ".join(str(model[key]) for key in ["provider", "id", "variant"] if key in model)
        if model_text:
            lines.append(f"Model: {model_text}")

    tokens = metadata.get("tokens", {})
    if tokens:
        token_text = ", ".join(f"{key}={value}" for key, value in tokens.items())
        lines.append(f"Tokens: {token_text}")

    time_data = metadata.get("time", {})
    if time_data.get("created"):
        lines.append(f"Created: {time_data['created']}")
    if time_data.get("updated"):
        lines.append(f"Updated: {time_data['updated']}")

    lines.extend(["", "## Transcript", ""])
    for index, message in enumerate(messages, start=1):
        label = "User" if message["role"] == "user" else "Assistant"
        lines.extend([f"## {index}. {label}", "", message["text"].rstrip(), ""])
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="OpenCode share URL or saved HTML file")
    parser.add_argument("--out", help="Write clean Markdown transcript to this path")
    parser.add_argument("--json-out", help="Write extracted messages as JSON")
    args = parser.parse_args()

    try:
        page, resolved_source = read_source(args.source)
        metadata = extract_metadata(page, resolved_source)
        messages = parse_session(page)
    except ShareExtractError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code

    markdown = to_markdown(messages, metadata)

    if args.out:
        Path(args.out).write_text(markdown, encoding="utf-8")
    else:
        sys.stdout.write(markdown)

    if args.json_out:
        payload = {"metadata": metadata, "message_count": len(messages), "messages": messages}
        Path(args.json_out).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    user_count = sum(1 for message in messages if message["role"] == "user")
    assistant_count = sum(1 for message in messages if message["role"] == "assistant")
    print(f"extracted={len(messages)} user={user_count} assistant={assistant_count}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
