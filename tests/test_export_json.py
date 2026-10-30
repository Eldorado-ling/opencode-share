"""Tests for the native OpenCode session export converter.

The converter turns the JSON file that ``opencode session export`` writes into
a filtered conversation view.  Every fixture in this module is synthetic: no
real session, no real history, no network access and no credential is used.

Non-ASCII characters are written as escapes, so this module stays ASCII-only
and cannot be corrupted by a Windows console code page when a failure message
is printed.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
SCRIPT_PATH = SCRIPTS_DIR / "extract_opencode_export.py"
LEGACY_SCRIPT_PATH = SCRIPTS_DIR / "extract_opencode_share.py"
EXAMPLE_PATH = REPO_ROOT / "examples" / "opencode-v2.synthetic.json"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import extract_opencode_export as converter  # noqa: E402


# --- synthetic data -------------------------------------------------------

#: Visible text that mixes HTML entities, indentation, a newline, a dash, CJK
#: characters and an emoji.
FIDELITY_TEXT = (
    "Keep &amp; entities, indentation\n    and newlines \u2014 \u4f60\u597d \U0001f642"
)

#: The placeholder that a native ``--sanitize`` export writes.
SANITIZED_TEXT = "<session-data-redacted>"

#: Text that a tool returned.  It must never reach the output.
NESTED_TOOL_TEXT = "Nested tool output that must not appear anywhere."

#: Text of a reasoning block.  It must never reach the output.
REASONING_TEXT = "Internal reasoning that must not appear anywhere."

#: Every known message type that is not conversation text.
KNOWN_IGNORED_TYPES = (
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

#: The complete Markdown the bundled example has to produce.
EXPECTED_MARKDOWN = (
    "# OpenCode Session Export - Filtered Conversation\n"
    "\n"
    "Filtered view of a native OpenCode session export. It is not a full archive\n"
    "and it is not secret redaction: secrets that were already part of the\n"
    "visible text stay in the text.\n"
    "\n"
    "## Summary\n"
    "\n"
    "- Input kind: native OpenCode session export (JSON)\n"
    "- Source messages: 4\n"
    "- Retained messages: 2\n"
    "- Omitted messages without visible text: 0\n"
    "- Omitted message types: system 1, compaction 1\n"
    "- Omitted assistant blocks: reasoning 1, tool 1\n"
    "- User attachments: 0 (names, paths and contents are not included)\n"
    "\n"
    "## Conversation\n"
    "\n"
    "### 1. User\n"
    "\n"
    "Please summarize this synthetic conversation.\n"
    "\n"
    "### 2. Assistant\n"
    "\n"
    "First visible answer block.\n"
    "\n"
    "Second visible answer block.\n"
)

#: The complete normalized JSON the bundled example has to produce.
EXPECTED_JSON = """{
  "format": "opencode-session-export-conversation",
  "version": 1,
  "note": "Filtered conversation view of an OpenCode session export. Not a full archive and not secret redaction.",
  "summary": {
    "source_messages": 4,
    "retained_messages": 2,
    "omitted_messages": 0,
    "ignored_messages": 2,
    "ignored_message_types": {
      "system": 1,
      "compaction": 1
    },
    "omitted_assistant_blocks": {
      "reasoning": 1,
      "tool": 1
    },
    "user_attachments": 0
  },
  "messages": [
    {
      "source_index": 0,
      "role": "user",
      "text": "Please summarize this synthetic conversation."
    },
    {
      "source_index": 2,
      "role": "assistant",
      "text": "First visible answer block.\\n\\nSecond visible answer block."
    }
  ]
}
"""


def build_export(messages: list[dict]) -> dict:
    """Build a synthetic export envelope around a list of messages."""
    return {
        "info": {
            "id": "ses_synthetic_fixture",
            "title": "Synthetic Fixture Session",
            "directory": "/synthetic/project",
        },
        "messages": messages,
    }


def user_message(text: str, message_id: str = "msg_synthetic_001", **extra) -> dict:
    """Build a synthetic user message."""
    message = {"id": message_id, "type": "user", "text": text}
    message.update(extra)
    return message


def assistant_message(content: list[dict], message_id: str = "msg_synthetic_002") -> dict:
    """Build a synthetic assistant message."""
    return {"id": message_id, "type": "assistant", "content": content}


def text_block(text: str) -> dict:
    """Build a visible assistant text block."""
    return {"type": "text", "text": text}


def tool_block(output: str = NESTED_TOOL_TEXT) -> dict:
    """Build a tool block with nested private input and output."""
    return {
        "type": "tool",
        "callID": "call_synthetic_001",
        "tool": "read",
        "state": {
            "status": "completed",
            "input": {"filePath": "/synthetic/project/notes.md"},
            "output": output,
        },
    }


def run_cli(*arguments: str) -> subprocess.CompletedProcess:
    """Run the converter as a real subprocess and capture its raw output."""
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *arguments],
        cwd=str(REPO_ROOT),
        capture_output=True,
    )


class MessageOrderTests(unittest.TestCase):
    """The order of the exported array is the order of the conversation."""

    def test_array_order_wins_over_lexically_inverted_ids(self):
        export = build_export(
            [
                user_message("first", "msg_zulu"),
                assistant_message([text_block("second")], "msg_alpha"),
                user_message("third", "msg_mike"),
            ]
        )
        retained, summary = converter.extract_conversation(export["messages"])
        self.assertEqual(
            [message["text"] for message in retained], ["first", "second", "third"]
        )
        self.assertEqual(
            [message["source_index"] for message in retained], [0, 1, 2]
        )
        self.assertEqual(summary["retained_messages"], 3)

    def test_ids_are_not_sorted(self):
        export = build_export(
            [
                user_message("kept first", "msg_zzz"),
                user_message("kept second", "msg_aaa"),
            ]
        )
        retained, _ = converter.extract_conversation(export["messages"])
        self.assertEqual(
            [message["text"] for message in retained], ["kept first", "kept second"]
        )

    def test_assistant_text_blocks_are_joined_with_a_blank_line(self):
        export = build_export(
            [
                assistant_message(
                    [text_block("first block"), text_block("second block")]
                )
            ]
        )
        retained, _ = converter.extract_conversation(export["messages"])
        self.assertEqual(retained[0]["text"], "first block\n\nsecond block")

    def test_nested_tool_text_is_not_leaked(self):
        export = build_export(
            [
                assistant_message(
                    [
                        {"type": "reasoning", "text": REASONING_TEXT},
                        tool_block(),
                        text_block("visible answer"),
                    ]
                )
            ]
        )
        retained, summary = converter.extract_conversation(export["messages"])
        self.assertEqual(retained[0]["text"], "visible answer")
        self.assertNotIn(NESTED_TOOL_TEXT, retained[0]["text"])
        self.assertNotIn(REASONING_TEXT, retained[0]["text"])
        self.assertEqual(summary["omitted_assistant_blocks"], {"reasoning": 1, "tool": 1})

    def test_nested_tool_text_is_not_leaked_into_the_rendered_output(self):
        export = build_export([assistant_message([tool_block(), text_block("answer")])])
        retained, summary = converter.extract_conversation(export["messages"])
        markdown = converter.render_markdown(retained, summary)
        normalized = converter.render_json(retained, summary)
        for rendered in (markdown, normalized):
            self.assertNotIn(NESTED_TOOL_TEXT, rendered)
            self.assertNotIn(REASONING_TEXT, rendered)
            self.assertNotIn("/synthetic/project/notes.md", rendered)


class IgnoredKindTests(unittest.TestCase):
    """Everything that is not conversation text is omitted and counted."""

    def test_every_known_ignored_kind_is_counted(self):
        export = build_export(
            [{"id": f"msg_{name}", "type": name} for name in KNOWN_IGNORED_TYPES]
        )
        retained, summary = converter.extract_conversation(export["messages"])
        self.assertEqual(retained, [])
        self.assertEqual(
            summary["ignored_message_types"], {name: 1 for name in KNOWN_IGNORED_TYPES}
        )
        self.assertEqual(summary["ignored_messages"], len(KNOWN_IGNORED_TYPES))
        self.assertEqual(summary["source_messages"], len(KNOWN_IGNORED_TYPES))

    def test_ignored_message_text_never_reaches_the_output(self):
        secret = "system prompt that must not appear"
        export = build_export(
            [{"id": "msg_system", "type": "system", "text": secret}]
        )
        retained, summary = converter.extract_conversation(export["messages"])
        markdown = converter.render_markdown(retained, summary)
        self.assertNotIn(secret, markdown)

    def test_messages_without_visible_text_are_omitted_and_counted(self):
        export = build_export(
            [
                user_message(""),
                user_message("   "),
                assistant_message([]),
                assistant_message([{"type": "reasoning", "text": REASONING_TEXT}]),
            ]
        )
        retained, summary = converter.extract_conversation(export["messages"])
        self.assertEqual(retained, [])
        self.assertEqual(summary["omitted_messages"], 4)
        self.assertEqual(summary["retained_messages"], 0)

    def test_attachments_only_user_message_is_counted_without_names(self):
        export = build_export(
            [
                user_message(
                    "",
                    files=[{"filename": "private-notes.md", "path": "/synthetic/x"}],
                )
            ]
        )
        retained, summary = converter.extract_conversation(export["messages"])
        self.assertEqual(retained, [])
        self.assertEqual(summary["user_attachments"], 1)
        self.assertEqual(summary["omitted_messages"], 1)
        markdown = converter.render_markdown(retained, summary)
        self.assertNotIn("private-notes.md", markdown)
        self.assertNotIn("/synthetic/x", markdown)

    def test_attachment_count_is_the_sum_over_user_messages(self):
        export = build_export(
            [
                user_message("hello", files=[{"filename": "a"}, {"filename": "b"}]),
                user_message("", files=[{"filename": "c"}]),
            ]
        )
        _, summary = converter.extract_conversation(export["messages"])
        self.assertEqual(summary["user_attachments"], 3)

    def test_summary_accounts_for_every_message(self):
        export = build_export(
            [
                user_message("visible"),
                {"id": "msg_system", "type": "system"},
                user_message(""),
            ]
        )
        _, summary = converter.extract_conversation(export["messages"])
        self.assertEqual(
            summary["source_messages"],
            summary["retained_messages"]
            + summary["omitted_messages"]
            + summary["ignored_messages"],
        )


class FidelityTests(unittest.TestCase):
    """Visible text is copied verbatim."""

    def test_unicode_entities_and_indentation_survive(self):
        export = build_export([user_message(FIDELITY_TEXT)])
        retained, _ = converter.extract_conversation(export["messages"])
        self.assertEqual(retained[0]["text"], FIDELITY_TEXT)
        self.assertIn("&amp;", retained[0]["text"])
        self.assertIn("\n    and newlines", retained[0]["text"])

    def test_sanitized_placeholder_is_kept_verbatim(self):
        export = build_export([user_message(SANITIZED_TEXT)])
        retained, summary = converter.extract_conversation(export["messages"])
        self.assertEqual(retained[0]["text"], SANITIZED_TEXT)
        markdown = converter.render_markdown(retained, summary)
        self.assertIn(SANITIZED_TEXT, markdown)

    def test_text_is_not_unescaped_or_mojibake_repaired(self):
        export = build_export([user_message("caf\u00e9 &amp; &lt;b&gt;")])
        retained, _ = converter.extract_conversation(export["messages"])
        self.assertEqual(retained[0]["text"], "caf\u00e9 &amp; &lt;b&gt;")

    def test_metadata_is_not_copied_into_the_output(self):
        export = build_export(
            [
                {
                    "id": "msg_synthetic_001",
                    "sessionID": "ses_synthetic_fixture",
                    "type": "user",
                    "text": "visible",
                    "cost": 1.25,
                    "tokens": {"input": 10, "output": 20},
                }
            ]
        )
        retained, summary = converter.extract_conversation(export["messages"])
        for rendered in (
            converter.render_markdown(retained, summary),
            converter.render_json(retained, summary),
        ):
            self.assertNotIn("ses_synthetic_fixture", rendered)
            self.assertNotIn("cost", rendered)
            self.assertNotIn("tokens", rendered)


class ValidationTests(unittest.TestCase):
    """Unsupported or malformed input is rejected explicitly."""

    def assert_rejected(self, messages: list, fragment: str = "") -> None:
        """Assert that a message list is rejected with a concise error."""
        with self.assertRaises(converter.ExportError) as caught:
            converter.extract_conversation(messages)
        message = str(caught.exception)
        self.assertTrue(message, "the error message must not be empty")
        if fragment:
            self.assertIn(fragment, message)

    def test_unknown_message_type_is_rejected(self):
        self.assert_rejected([{"id": "m1", "type": "chat"}], "unsupported message type")

    def test_missing_message_type_is_rejected(self):
        self.assert_rejected([{"id": "m1", "text": "hello"}], "missing 'type'")

    def test_legacy_v1_message_shape_is_rejected(self):
        self.assert_rejected(
            [{"info": {"role": "user"}, "parts": [{"type": "text", "text": "x"}]}],
            "legacy export shape",
        )

    def test_unknown_assistant_block_type_is_rejected(self):
        self.assert_rejected(
            [assistant_message([{"type": "image", "url": "synthetic"}])],
            "unsupported assistant content block type",
        )

    def test_malformed_user_text_is_rejected(self):
        self.assert_rejected([{"id": "m1", "type": "user", "text": 42}], "'text' string")
        self.assert_rejected([{"id": "m1", "type": "user"}], "'text' string")
        self.assert_rejected(
            [{"id": "m1", "type": "user", "text": "x", "files": "not-a-list"}],
            "'files' must be an array",
        )

    def test_malformed_assistant_content_is_rejected(self):
        self.assert_rejected(
            [{"id": "m1", "type": "assistant", "content": "text"}], "'content' array"
        )
        self.assert_rejected(
            [{"id": "m1", "type": "assistant"}], "'content' array"
        )
        self.assert_rejected(
            [assistant_message([{"type": "text"}])], "'text' string"
        )

    def test_message_that_is_not_an_object_is_rejected(self):
        self.assert_rejected(["not a message"], "must be an object")

    def test_error_message_does_not_dump_source_content(self):
        with self.assertRaises(converter.ExportError) as caught:
            converter.extract_conversation(
                [user_message("SECRET-VALUE"), assistant_message("not a list")]
            )
        message = str(caught.exception)
        self.assertNotIn("SECRET-VALUE", message)
        self.assertNotIn("not a list", message)


class RootShapeTests(unittest.TestCase):
    """The root of an export needs an info object and a messages array."""

    def test_missing_info_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "session.json"
            source.write_text(json.dumps({"messages": []}), encoding="utf-8")
            with self.assertRaises(converter.ExportError) as caught:
                converter.load_export(source)
        self.assertIn("'info'", str(caught.exception))

    def test_info_must_be_an_object(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "session.json"
            source.write_text(
                json.dumps({"info": [], "messages": []}), encoding="utf-8"
            )
            with self.assertRaises(converter.ExportError) as caught:
                converter.load_export(source)
        self.assertIn("'info'", str(caught.exception))

    def test_cli_rejects_missing_info_and_creates_no_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = tmp / "session.json"
            source.write_text(
                json.dumps(
                    {"messages": [{"id": "m1", "type": "user", "text": "visible"}]}
                ),
                encoding="utf-8",
            )
            markdown_path = tmp / "clean.md"
            json_path = tmp / "clean.json"
            result = run_cli(
                str(source), "--out", str(markdown_path), "--json-out", str(json_path)
            )
            self.assertEqual(result.returncode, converter.EXIT_INPUT_ERROR)
            self.assertFalse(markdown_path.exists())
            self.assertFalse(json_path.exists())

    def test_cli_rejects_info_that_is_not_an_object_and_creates_no_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = tmp / "session.json"
            source.write_text(
                json.dumps({"info": "not an object", "messages": []}), encoding="utf-8"
            )
            markdown_path = tmp / "clean.md"
            result = run_cli(str(source), "--out", str(markdown_path))
            self.assertEqual(result.returncode, converter.EXIT_INPUT_ERROR)
            self.assertFalse(markdown_path.exists())


class ErrorMessageLeakTests(unittest.TestCase):
    """A rejected export must not repeat its own content in the error."""

    #: Values that look harmless but still come out of the exported file.
    UNKNOWN_VALUES = (
        "SYNTHETIC_SECRET_VALUE",
        "sk-demo-123",
        "MARKER_HEAD\nMARKER_TAIL",
    )

    def assert_not_echoed(self, messages: list, marker: str) -> None:
        """Assert that a rejected export does not repeat the given value."""
        with self.assertRaises(converter.ExportError) as caught:
            converter.extract_conversation(messages)
        message = str(caught.exception)
        self.assertNotIn(marker, message)
        for line in marker.split("\n"):
            self.assertNotIn(line, message)
        self.assertNotIn("\n", message)

    def test_unknown_message_type_value_is_not_echoed(self):
        for marker in self.UNKNOWN_VALUES:
            with self.subTest(marker=marker):
                self.assert_not_echoed([{"id": "m1", "type": marker}], marker)

    def test_unknown_block_type_value_is_not_echoed(self):
        for marker in self.UNKNOWN_VALUES:
            with self.subTest(marker=marker):
                self.assert_not_echoed(
                    [assistant_message([{"type": marker, "text": "x"}])], marker
                )

    def test_unknown_type_value_is_not_echoed_by_the_cli(self):
        for marker in self.UNKNOWN_VALUES:
            with self.subTest(marker=marker):
                with tempfile.TemporaryDirectory() as tmpdir:
                    tmp = Path(tmpdir)
                    source = tmp / "session.json"
                    source.write_text(
                        json.dumps(build_export([{"id": "m1", "type": marker}])),
                        encoding="utf-8",
                    )
                    result = run_cli(str(source))
                stderr = result.stderr.decode("utf-8")
                self.assertEqual(result.returncode, converter.EXIT_INPUT_ERROR)
                self.assertNotIn(marker, stderr)
                for line in marker.split("\n"):
                    self.assertNotIn(line, stderr)
                self.assertIn("supported types are", stderr)

    def test_unknown_block_type_value_is_not_echoed_by_the_cli(self):
        for marker in self.UNKNOWN_VALUES:
            with self.subTest(marker=marker):
                with tempfile.TemporaryDirectory() as tmpdir:
                    tmp = Path(tmpdir)
                    source = tmp / "session.json"
                    source.write_text(
                        json.dumps(
                            build_export(
                                [assistant_message([{"type": marker, "text": "x"}])]
                            )
                        ),
                        encoding="utf-8",
                    )
                    result = run_cli(str(source))
                stderr = result.stderr.decode("utf-8")
                self.assertEqual(result.returncode, converter.EXIT_INPUT_ERROR)
                self.assertNotIn(marker, stderr)
                for line in marker.split("\n"):
                    self.assertNotIn(line, stderr)
                self.assertIn("supported types are", stderr)


class CliTests(unittest.TestCase):
    """The command line interface of the converter."""

    def write_json(self, directory: Path, name: str, payload) -> Path:
        """Write a synthetic export into a temporary directory."""
        path = directory / name
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def test_bundled_example_produces_the_expected_markdown_and_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            markdown_path = tmp / "clean.md"
            json_path = tmp / "clean.json"

            result = run_cli(
                str(EXAMPLE_PATH),
                "--out",
                str(markdown_path),
                "--json-out",
                str(json_path),
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
            markdown = markdown_path.read_text(encoding="utf-8")
            normalized = json_path.read_text(encoding="utf-8")

        self.assertEqual(markdown, EXPECTED_MARKDOWN)
        self.assertEqual(normalized, EXPECTED_JSON)
        self.assertEqual(
            json.loads(normalized)["messages"][1]["text"],
            "First visible answer block.\n\nSecond visible answer block.",
        )

    def test_bundled_example_contains_no_private_content_in_the_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            markdown_path = tmp / "clean.md"
            result = run_cli(str(EXAMPLE_PATH), "--out", str(markdown_path))
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
            markdown = markdown_path.read_text(encoding="utf-8")

        for private in (
            "SYNTHETIC_SYSTEM_CONTEXT",
            "SYNTHETIC_REASONING",
            "SYNTHETIC_TOOL_OUTPUT",
            "SYNTHETIC_COMPACTION",
            "/synthetic/project/example.txt",
            "ses_synthetic_fixture",
            "Synthetic fixture",
            "projectID",
            "providerID",
            "example_read",
            "call_synthetic",
            "manual",
            "global",
        ):
            with self.subTest(private=private):
                self.assertNotIn(private, markdown)

    def test_stdout_is_utf8_even_on_windows(self):
        result = run_cli(str(EXAMPLE_PATH))
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        stdout = result.stdout.decode("utf-8")
        self.assertEqual(stdout, EXPECTED_MARKDOWN)

    def test_utf8_bom_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = tmp / "session.json"
            source.write_bytes(
                b"\xef\xbb\xbf" + EXAMPLE_PATH.read_bytes()
            )
            markdown_path = tmp / "clean.md"
            result = run_cli(str(source), "--out", str(markdown_path))
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
            markdown = markdown_path.read_text(encoding="utf-8")

        self.assertEqual(markdown, EXPECTED_MARKDOWN)

    def test_invalid_json_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = tmp / "broken.json"
            source.write_text("{not json", encoding="utf-8")
            result = run_cli(str(source))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.returncode, converter.EXIT_INPUT_ERROR)

    def test_invalid_encoding_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = tmp / "broken.json"
            source.write_bytes(b"\xff\xfe\x00\x00")
            result = run_cli(str(source))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.returncode, converter.EXIT_INPUT_ERROR)

    def test_wrong_root_shape_is_rejected(self):
        for payload in (
            "[]",
            '{"info":{}}',
            '{"info":[],"messages":{}}',
            '{"messages":[]}',
            '{"messages":[],"info":null}',
        ):
            with self.subTest(payload=payload):
                with tempfile.TemporaryDirectory() as tmpdir:
                    tmp = Path(tmpdir)
                    source = tmp / "session.json"
                    source.write_text(payload, encoding="utf-8")
                    result = run_cli(str(source))
                self.assertEqual(result.returncode, converter.EXIT_INPUT_ERROR)

    def test_missing_input_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_cli(str(Path(tmpdir) / "missing.json"))
        self.assertEqual(result.returncode, converter.EXIT_INPUT_ERROR)

    def test_output_must_not_alias_the_input(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = tmp / "session.json"
            source.write_bytes(EXAMPLE_PATH.read_bytes())
            before = source.read_bytes()
            result = run_cli(str(source), "--out", str(source))
            self.assertEqual(result.returncode, converter.EXIT_OUTPUT_ERROR)
            self.assertEqual(source.read_bytes(), before)

    def test_output_must_not_alias_the_input_through_a_relative_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = tmp / "session.json"
            source.write_bytes(EXAMPLE_PATH.read_bytes())
            nested = tmp / "nested"
            nested.mkdir()
            aliased = nested / ".." / "session.json"
            result = run_cli(str(source), "--out", str(aliased))
            self.assertEqual(result.returncode, converter.EXIT_OUTPUT_ERROR)
            self.assertTrue(source.exists())

    def test_existing_output_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            markdown_path = tmp / "clean.md"
            markdown_path.write_text("KEEP ME", encoding="utf-8")
            result = run_cli(str(EXAMPLE_PATH), "--out", str(markdown_path))
            self.assertEqual(result.returncode, converter.EXIT_OUTPUT_ERROR)
            self.assertEqual(markdown_path.read_text(encoding="utf-8"), "KEEP ME")

    def test_output_paths_must_not_alias_each_other(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            shared = tmp / "same.txt"
            result = run_cli(
                str(EXAMPLE_PATH), "--out", str(shared), "--json-out", str(shared)
            )
            self.assertEqual(result.returncode, converter.EXIT_OUTPUT_ERROR)
            self.assertFalse(shared.exists())

    def test_invalid_input_creates_neither_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = tmp / "broken.json"
            source.write_text('{"info":{},"messages":[{"type":"nope"}]}', encoding="utf-8")
            markdown_path = tmp / "clean.md"
            json_path = tmp / "clean.json"
            result = run_cli(
                str(source), "--out", str(markdown_path), "--json-out", str(json_path)
            )
            self.assertEqual(result.returncode, converter.EXIT_INPUT_ERROR)
            self.assertFalse(markdown_path.exists())
            self.assertFalse(json_path.exists())

    def test_output_is_written_without_a_byte_order_mark(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            markdown_path = tmp / "clean.md"
            json_path = tmp / "clean.json"
            result = run_cli(
                str(EXAMPLE_PATH),
                "--out",
                str(markdown_path),
                "--json-out",
                str(json_path),
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
            self.assertFalse(markdown_path.read_bytes().startswith(b"\xef\xbb\xbf"))
            self.assertFalse(json_path.read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_empty_export_produces_an_empty_conversation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = self.write_json(tmp, "empty.json", build_export([]))
            markdown_path = tmp / "clean.md"
            result = run_cli(str(source), "--out", str(markdown_path))
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
            markdown = markdown_path.read_text(encoding="utf-8")

        self.assertIn("- Source messages: 0", markdown)
        self.assertIn("- Retained messages: 0", markdown)
        self.assertIn("- (no visible conversation text)", markdown)


class LegacyRouteTests(unittest.TestCase):
    """The JSON route and the legacy saved-HTML route do not overlap."""

    def test_legacy_html_tool_does_not_accept_the_native_json(self):
        result = subprocess.run(
            [sys.executable, str(LEGACY_SCRIPT_PATH), str(EXAMPLE_PATH)],
            cwd=str(REPO_ROOT),
            capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)

    def test_json_tool_does_not_accept_the_legacy_v1_export(self):
        legacy_export = {
            "info": {"id": "ses_legacy"},
            "messages": [
                {
                    "info": {"role": "user", "id": "msg_legacy_001"},
                    "parts": [{"type": "text", "text": "legacy text"}],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = tmp / "legacy.json"
            source.write_text(json.dumps(legacy_export), encoding="utf-8")
            result = run_cli(str(source))
            self.assertEqual(result.returncode, converter.EXIT_INPUT_ERROR)
            self.assertIn(b"legacy", result.stderr.lower())


if __name__ == "__main__":
    unittest.main()
