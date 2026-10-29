"""Regression tests for lossless Unicode handling in the share extractor.

The extractor repairs mojibake (UTF-8 bytes that were decoded as Latin-1).
That repair must never drop characters: if the text cannot be re-encoded
without loss, it has to be returned unchanged.

All data used here is synthetic. Non-ASCII characters are written as escapes
so this module stays ASCII-only and cannot be corrupted by a Windows console
codepage when a failure message is printed.
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

#: Valid CJK text ("nihao shijie").
CJK_TEXT = "\u4f60\u597d\u4e16\u754c"

#: The same text after its UTF-8 bytes were decoded as Latin-1.
MOJIBAKE_CJK = CJK_TEXT.encode("utf-8").decode("latin-1")

#: Mojibake of a two character CJK word.
MOJIBAKE_PAIR = "\u4f60\u597d".encode("utf-8").decode("latin-1")

#: Emoji, outside the Latin-1 range.
EMOJI = "\U0001f642"

#: Non-Latin script (Cyrillic).
CYRILLIC = "\u041f\u0440\u0438\u0432\u0435\u0442"

#: Combining acute accent.
COMBINING_ACUTE = "\u0301"

#: Latin-1 range character ("e" with acute).
LATIN1_ACCENT = "\u00e9"

#: Text mixing every risky character class in one string.
MIXED_TEXT = (
    CJK_TEXT
    + " "
    + EMOJI
    + " caf"
    + LATIN1_ACCENT
    + " e"
    + COMBINING_ACUTE
    + " "
    + CYRILLIC
    + " "
    + MOJIBAKE_PAIR
)

#: Smaller mixed text (valid script plus an emoji).
MIXED_SHORT = CJK_TEXT + " " + EMOJI

#: Mojibake with a trailing emoji: the emoji must survive the repair attempt.
MOJIBAKE_WITH_EMOJI = MOJIBAKE_PAIR + EMOJI

#: A tiny synthetic share page in the format the parser already supports.
FIXTURE_TEMPLATE = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Synthetic share fixture</title></head>
<body>
<script>self.__next_f.push([0,"getShareData"]);</script>
<script>
session:$R[1]=[$R[2]={shareID:"syn_share_001",id:"ses_syn0001",title:"Synthetic Unicode Fixture",directory:"/synthetic/demo",agent:"demo-agent",version:"0.0.1",model:$R[3]={id:"demo-model",providerID:"demo-provider"},cost:1.25,tokens:$R[4]={input:1200,output:2400,reasoning:300},time:$R[5]={created:1700000000000,updated:1700000060000}}];
</script>
<script>
$R[10]={role:"user",id:"msg_user1",parts:{msg_user1:$R[11]=[{type:"text",text:"__MIXED__"}]},sessionID:"ses_syn0001"};
$R[20]={role:"assistant",id:"msg_asst1",parts:{msg_asst1:$R[21]=[{type:"text",text:"__MOJIBAKE__"}]}};
$R[30]={role:"user",id:"msg_user2",parts:{msg_user2:$R[31]=[{type:"text",text:"__MOJIBAKE_EMOJI__"}]}};
$R[40]={role:"assistant",id:"msg_asst2",parts:{msg_asst2:$R[41]=[{type:"text",text:"__MIXED_SHORT__"}]}};
</script>
</body>
</html>
"""


def build_fixture() -> str:
    return (
        FIXTURE_TEMPLATE.replace("__MIXED__", MIXED_TEXT)
        .replace("__MOJIBAKE__", MOJIBAKE_CJK)
        .replace("__MOJIBAKE_EMOJI__", MOJIBAKE_WITH_EMOJI)
        .replace("__MIXED_SHORT__", MIXED_SHORT)
    )


class MojibakeRepairTests(unittest.TestCase):
    """fix_mojibake() must repair what it can and never lose characters."""

    def test_pure_mojibake_cjk_is_repaired(self):
        self.assertEqual(extractor.fix_mojibake(MOJIBAKE_CJK), CJK_TEXT)

    def test_mojibake_followed_by_emoji_is_preserved(self):
        mixed = MOJIBAKE_PAIR + EMOJI
        self.assertEqual(extractor.fix_mojibake(mixed), mixed)

    def test_valid_cjk_before_mojibake_is_preserved(self):
        mixed = CJK_TEXT + MOJIBAKE_PAIR
        self.assertEqual(extractor.fix_mojibake(mixed), mixed)

    def test_non_latin_script_is_preserved(self):
        mixed = "caf" + LATIN1_ACCENT + " " + CYRILLIC + " " + MOJIBAKE_PAIR
        self.assertEqual(extractor.fix_mojibake(mixed), mixed)

    def test_combining_marks_are_preserved(self):
        mixed = "cafe" + COMBINING_ACUTE + " " + MOJIBAKE_PAIR
        self.assertEqual(extractor.fix_mojibake(mixed), mixed)

    def test_plain_ascii_is_unchanged(self):
        text = "plain ascii text 123 !?"
        self.assertEqual(extractor.fix_mojibake(text), text)

    def test_accented_latin1_text_is_unchanged(self):
        text = "caf" + LATIN1_ACCENT + " na" + "\u00ef" + "ve r" + "\u00e9" + "sum" + "\u00e9"
        self.assertEqual(extractor.fix_mojibake(text), text)

    def test_unicode_control_characters_are_unchanged(self):
        text = "a\u0000b\u2028c\u200bd" + LATIN1_ACCENT
        self.assertEqual(extractor.fix_mojibake(text), text)


class CleanTextTests(unittest.TestCase):
    """clean_text() keeps its unescaping/newline behaviour and loses nothing."""

    def test_mixed_unicode_is_preserved(self):
        self.assertEqual(extractor.clean_text(MIXED_TEXT), MIXED_TEXT)

    def test_pure_mojibake_is_repaired(self):
        self.assertEqual(extractor.clean_text(MOJIBAKE_CJK), CJK_TEXT)

    def test_html_entities_are_unescaped(self):
        self.assertEqual(extractor.clean_text("a &amp; b &lt;c&gt;"), "a & b <c>")

    def test_newlines_are_normalized(self):
        self.assertEqual(extractor.clean_text("a\r\nb\rc\nd"), "a\nb\nc\nd")

    def test_emoji_and_accented_text_survive_cleaning(self):
        text = EMOJI + " caf" + LATIN1_ACCENT + " " + CJK_TEXT
        self.assertEqual(extractor.clean_text(text), text)


class JsFieldTests(unittest.TestCase):
    """Fields read out of the embedded share payload keep their characters."""

    def test_mixed_unicode_field_is_preserved(self):
        self.assertEqual(extractor.js_field('text:"' + MIXED_TEXT + '"', "text"), MIXED_TEXT)

    def test_pure_mojibake_field_is_repaired(self):
        self.assertEqual(
            extractor.js_field('text:"' + MOJIBAKE_CJK + '"', "text"),
            CJK_TEXT,
        )


class CliExtractionTests(unittest.TestCase):
    """End to end extraction from a saved share page, in both output formats."""

    def test_cli_preserves_mixed_text_in_markdown_and_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            html_path = tmp / "share.html"
            markdown_path = tmp / "clean.md"
            json_path = tmp / "clean.json"
            html_path.write_text(build_fixture(), encoding="utf-8")

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
            json_text = json_path.read_text(encoding="utf-8")
            payload = json.loads(json_text)

            self.assertEqual(payload["message_count"], 4)
            self.assertEqual(
                [message["role"] for message in payload["messages"]],
                ["user", "assistant", "user", "assistant"],
            )
            self.assertEqual(
                [message["text"] for message in payload["messages"]],
                [MIXED_TEXT, CJK_TEXT, MOJIBAKE_WITH_EMOJI, MIXED_SHORT],
            )

            # Markdown keeps the same characters, including the emoji.
            self.assertIn(MIXED_TEXT, markdown)
            self.assertIn(MOJIBAKE_WITH_EMOJI, markdown)
            self.assertIn(MIXED_SHORT, markdown)
            self.assertIn(EMOJI, markdown)

            # JSON is written as UTF-8 without escaping non-ASCII characters.
            self.assertIn(EMOJI, json_text)


if __name__ == "__main__":
    unittest.main()
