"""Boundary tests for the serialized message parts arrays.

A share page stores every message as a serialized object whose visible text
lives in that message's own parts array. The parser therefore has to find the
real end of each array before it reads the text out of it. A parts array may
be arbitrarily long, may contain nested references and nested arrays, and may
contain quoted strings with brackets inside them.

These tests only use synthetic data. Nothing is fetched, and no real session
is involved.
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
SCRIPT_PATH = SCRIPTS_DIR / "extract_opencode_share.py"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import extract_opencode_share as extractor  # noqa: E402


# --- synthetic data -------------------------------------------------------

#: A visible assistant answer that is longer than any fixed character limit.
LONG_TEXT = "START-" + ("x" * 250000) + "-END"

#: A long part that is not visible text, used to push the visible text of a
#: message past a fixed character limit.
LONG_REASONING = "r" * 250000

#: The serialized session object of the synthetic pages.
SESSION_OBJECT = (
    'session:$R[1]=[$R[2]={shareID:"syn_share_002",id:"ses_syn0002",'
    'title:"Synthetic Boundary Fixture",directory:"/synthetic/boundary",'
    'agent:"demo-agent",version:"0.0.1",'
    'model:$R[3]={id:"demo-model",providerID:"demo-provider"},cost:1.25,'
    'tokens:$R[4]={input:1200,output:2400,reasoning:300},'
    'time:$R[5]={created:1700000000000,updated:1700000060000}}];'
)

#: The metadata the synthetic pages carry.
EXPECTED_METADATA = {
    "share_id": "syn_share_002",
    "session_id": "ses_syn0002",
    "title": "Synthetic Boundary Fixture",
    "directory": "/synthetic/boundary",
    "agent": "demo-agent",
    "version": "0.0.1",
    "model": {"id": "demo-model", "provider": "demo-provider"},
    "cost": 1.25,
    "tokens": {"input": 1200, "output": 2400, "reasoning": 300},
    "time": {
        "created_ms": 1700000000000,
        "updated_ms": 1700000060000,
        "created": "2023-11-14T22:13:20+00:00",
        "updated": "2023-11-14T22:14:20+00:00",
    },
}


def build_page(
    messages: list[tuple], tail: str = "", prelude: tuple[str, ...] = ()
) -> str:
    """Build a synthetic saved share page.

    Every entry of ``messages`` is a tuple of ``(message id, role, parts body)``
    with an optional fourth element holding extra fields of the message object
    that sit outside the parts array. The parts body is the serialized content
    between the brackets of the message's parts array.

    ``tail`` is appended as a separate script block, so it can hold data that
    follows the last message. ``prelude`` holds the contents of script blocks
    that come before the payload.
    """
    lines = [
        "<!DOCTYPE html>",
        "<html>",
        '<head><meta charset="utf-8"><title>Synthetic boundary fixture</title></head>',
        "<body>",
    ]
    for script in prelude:
        lines.extend(["<script>", script, "</script>"])
    lines.extend(
        [
            '<script>self.__next_f.push([0,"getShareData"]);</script>',
            "<script>",
            SESSION_OBJECT,
            "</script>",
            "<script>",
        ]
    )
    for index, message in enumerate(messages):
        msg_id, role, parts_body = message[0], message[1], message[2]
        extra = message[3] if len(message) > 3 else ""
        reference = 100 + index * 10
        lines.append(
            '$R[%d]={role:"%s",id:"%s",parts:{%s:$R[%d]=[%s]%s}};'
            % (reference, role, msg_id, msg_id, reference + 1, parts_body, extra)
        )
    lines.append("</script>")
    if tail:
        lines.append("<script>")
        lines.append(tail)
        lines.append("</script>")
    lines.extend(["</body>", "</html>", ""])
    return "\n".join(lines)


def expected_markdown(source: str, messages: list[dict]) -> str:
    """The complete Markdown document the parser is expected to write."""
    lines = [
        "# OpenCode Share Session - Clean Transcript",
        "",
        "## Metadata",
        "",
        "Source: %s" % source,
        "Messages: %d" % len(messages),
        "Share ID: syn_share_002",
        "Session ID: ses_syn0002",
        "Title: Synthetic Boundary Fixture",
        "Directory: /synthetic/boundary",
        "Agent: demo-agent",
        "Version: 0.0.1",
        "Cost: 1.25",
        "Model: demo-provider / demo-model",
        "Tokens: input=1200, output=2400, reasoning=300",
        "Created: 2023-11-14T22:13:20+00:00",
        "Updated: 2023-11-14T22:14:20+00:00",
        "",
        "## Transcript",
        "",
    ]
    for index, message in enumerate(messages, start=1):
        label = "User" if message["role"] == "user" else "Assistant"
        lines.extend(["## %d. %s" % (index, label), "", message["text"].rstrip(), ""])
    return "\n".join(lines).rstrip() + "\n"


class TextAssertionCase(unittest.TestCase):
    """Shared helper for comparing long texts."""

    def assert_text_equals(self, actual: str, expected: str) -> None:
        """Compare long texts without dumping them into the test report."""
        self.assertEqual(len(actual), len(expected), "extracted text has a different length")
        self.assertTrue(actual == expected, "extracted text differs from the expected text")


class PartsArrayBoundaryTests(TextAssertionCase):
    """The visible text of a message comes from its own parts array."""

    def test_long_final_visible_text_is_preserved(self):
        page = build_page(
            [
                ("msg_user1", "user", '{type:"text",text:"question"}'),
                ("msg_asst1", "assistant", '{type:"text",text:"%s"}' % LONG_TEXT),
            ]
        )
        messages = extractor.parse_session(page)
        self.assertEqual([message["id"] for message in messages], ["msg_user1", "msg_asst1"])
        self.assertEqual([message["role"] for message in messages], ["user", "assistant"])
        self.assertEqual(messages[0]["text"], "question")
        self.assert_text_equals(messages[1]["text"], LONG_TEXT)

    def test_long_non_text_part_does_not_hide_the_visible_text(self):
        page = build_page(
            [
                ("msg_user1", "user", '{type:"text",text:"question"}'),
                (
                    "msg_asst1",
                    "assistant",
                    '{type:"reasoning",text:"%s"},{type:"text",text:"answer"}' % LONG_REASONING,
                ),
            ]
        )
        messages = extractor.parse_session(page)
        self.assertEqual([message["id"] for message in messages], ["msg_user1", "msg_asst1"])
        self.assertEqual([message["text"] for message in messages], ["question", "answer"])

    def test_message_order_and_earlier_messages_are_preserved(self):
        page = build_page(
            [
                ("msg_user1", "user", '{type:"text",text:"first"}'),
                ("msg_asst1", "assistant", '{type:"text",text:"second"}'),
                ("msg_user2", "user", '{type:"text",text:"third"}'),
                ("msg_asst2", "assistant", '{type:"text",text:"fourth"}'),
            ]
        )
        messages = extractor.parse_session(page)
        self.assertEqual(
            [(message["id"], message["role"], message["text"]) for message in messages],
            [
                ("msg_user1", "user", "first"),
                ("msg_asst1", "assistant", "second"),
                ("msg_user2", "user", "third"),
                ("msg_asst2", "assistant", "fourth"),
            ],
        )

    def test_quotes_backslashes_brackets_and_nested_references(self):
        page = build_page(
            [
                ("msg_user1", "user", '{type:"text",text:"question"}'),
                (
                    "msg_asst1",
                    "assistant",
                    '$R[12]={type:"text",text:"say \\"hi\\" and \\\\ and [x] {y}"}',
                ),
            ]
        )
        messages = extractor.parse_session(page)
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[1]["text"], 'say "hi" and \\ and [x] {y}')

    def test_message_key_inside_a_quoted_string_is_not_a_message(self):
        page = build_page(
            [
                (
                    "msg_asst1",
                    "assistant",
                    '{type:"text",text:"literal {msg_fake:$R[9]=[still text"}',
                )
            ]
        )
        messages = extractor.parse_session(page)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["id"], "msg_asst1")
        self.assertEqual(messages[0]["text"], "literal {msg_fake:$R[9]=[still text")

    def test_text_outside_the_parts_array_is_not_collected(self):
        page = build_page(
            [
                (
                    "msg_asst1",
                    "assistant",
                    '{type:"text",text:"visible"}',
                    ',summary:{type:"text",text:"NOT A PART"}',
                )
            ],
            tail='$R[900]={type:"text",text:"TRAILER NOT A PART"};',
        )
        messages = extractor.parse_session(page)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["text"], "visible")

    def test_unterminated_parts_array_does_not_invent_text(self):
        page = build_page(
            [("msg_user1", "user", '{type:"text",text:"question"}')],
            tail=(
                '$R[40]={role:"assistant",id:"msg_asst2",'
                'parts:{msg_asst2:$R[41]=[{type:"text",text:"half written"}'
            ),
        )
        messages = extractor.parse_session(page)
        self.assertEqual([message["id"] for message in messages], ["msg_user1"])
        self.assertNotIn("half written", json.dumps(messages))

    def test_unterminated_string_does_not_invent_text(self):
        page = build_page(
            [("msg_user1", "user", '{type:"text",text:"question"}')],
            tail=(
                '$R[40]={role:"assistant",id:"msg_asst2",'
                'parts:{msg_asst2:$R[41]=[{type:"text",text:"never closed}]};'
            ),
        )
        messages = extractor.parse_session(page)
        self.assertEqual([message["id"] for message in messages], ["msg_user1"])
        self.assertNotIn("never closed", json.dumps(messages))


class ScriptBoundaryTests(unittest.TestCase):
    """Only the JavaScript of a page is read as serialized data."""

    def test_double_quote_in_dom_text_does_not_hide_the_payload(self):
        page = build_page(
            [
                ("msg_user1", "user", '{type:"text",text:"question"}'),
                ("msg_asst1", "assistant", '{type:"text",text:"answer"}'),
            ]
        )
        quoted = page.replace("<body>", '<body><p>Someone said "hello</p>')
        messages = extractor.parse_session(quoted)
        self.assertEqual(
            [(message["id"], message["text"]) for message in messages],
            [("msg_user1", "question"), ("msg_asst1", "answer")],
        )

    def test_unrelated_script_does_not_hide_the_payload(self):
        page = build_page(
            [
                ("msg_user1", "user", '{type:"text",text:"question"}'),
                ("msg_asst1", "assistant", '{type:"text",text:"answer"}'),
            ],
            prelude=(
                'var note = "a quoted character";',
                'var broken = "an unterminated quote',
            ),
        )
        messages = extractor.parse_session(page)
        self.assertEqual(
            [(message["id"], message["text"]) for message in messages],
            [("msg_user1", "question"), ("msg_asst1", "answer")],
        )

    def test_raw_serialized_fragment_is_supported(self):
        fragment = 'msg_probe:$R[1]=[{type:"text",text:"hello"}]'
        self.assertEqual(extractor.extract_text_parts(fragment), {"msg_probe": "hello"})

    def test_raw_fragment_with_literal_script_tags_is_supported(self):
        fragment = 'msg_probe:$R[1]=[{type:"text",text:"literal <script>x</script>"}]'
        self.assertEqual(
            extractor.extract_text_parts(fragment),
            {"msg_probe": "literal <script>x</script>"},
        )

    def test_saved_page_prefix_is_still_recognized_as_markup(self):
        page = build_page(
            [
                ("msg_user1", "user", '{type:"text",text:"question"}'),
                ("msg_asst1", "assistant", '{type:"text",text:"answer"}'),
            ]
        )
        quoted = page.replace("<body>", '<body><p>Someone said "hello</p>')
        for prefix in ("\ufeff", "\ufeff\n  ", " \n\t"):
            with self.subTest(prefix=prefix):
                messages = extractor.parse_session(prefix + quoted)
                self.assertEqual(
                    [(message["id"], message["text"]) for message in messages],
                    [("msg_user1", "question"), ("msg_asst1", "answer")],
                )

    def test_message_key_needs_an_object_key_context(self):
        for fragment in (
            'xmsg_probe:$R[1]=[{type:"text",text:"hello"}]',
            'see msg_probe:$R[1]=[{type:"text",text:"hello"}] here',
        ):
            with self.subTest(fragment=fragment):
                self.assertEqual(extractor.extract_text_parts(fragment), {})


class CliBoundaryTests(TextAssertionCase):
    """The complete Markdown and JSON output of the parser."""

    def test_cli_writes_complete_markdown_and_json(self):
        messages = [
            {"id": "msg_user1", "role": "user", "text": "question"},
            {"id": "msg_asst1", "role": "assistant", "text": LONG_TEXT},
        ]
        page = build_page(
            [
                ("msg_user1", "user", '{type:"text",text:"question"}'),
                ("msg_asst1", "assistant", '{type:"text",text:"%s"}' % LONG_TEXT),
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            html_path = tmp / "share.html"
            markdown_path = tmp / "clean.md"
            json_path = tmp / "clean.json"
            html_path.write_text(page, encoding="utf-8")
            resolved_source = str(html_path.resolve())

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    str(html_path),
                    "--out",
                    str(markdown_path),
                    "--json-out",
                    str(json_path),
                ],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            markdown = markdown_path.read_text(encoding="utf-8")
            payload = json.loads(json_path.read_text(encoding="utf-8"))

        self.assert_text_equals(markdown, expected_markdown(resolved_source, messages))
        self.assertEqual(payload["message_count"], 2)
        self.assertEqual(
            [message["id"] for message in payload["messages"]],
            ["msg_user1", "msg_asst1"],
        )
        self.assertEqual(
            [message["role"] for message in payload["messages"]],
            ["user", "assistant"],
        )
        self.assert_text_equals(payload["messages"][0]["text"], "question")
        self.assert_text_equals(payload["messages"][1]["text"], LONG_TEXT)
        self.assertEqual(payload["metadata"], dict(EXPECTED_METADATA, source=resolved_source))


if __name__ == "__main__":
    unittest.main()
