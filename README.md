# OpenCode Share

Extract the meaningful transcript from a saved OpenCode share page.

## Status: legacy saved-HTML extractor

This skill is a **legacy saved-HTML extractor**. It reads the transcript out of
a saved OpenCode share page: the HTML file that a share URL used to return.

OpenCode's own sharing API is gone:

- The SDK documentation at <https://opencode.ai/docs/sdk/> states that
  `session.share` has been discontinued and now errors.
- The legacy changelog at <https://dev.opencode.ai/changelog/> records
  v1.19.1 (2026-10-15): official sharing and existing share links are
  unavailable.

So the supported workflow is offline: take a saved share page that you already
have and parse the file. The URL examples below are kept as historical
compatibility for pages and files that were saved earlier. A defunct share
link is not worth retrying, and this tool does not bring sharing back.

OpenCode v2.2.1 can export a session locally instead. `opencode session
export --help` lists a JSON export and a `--sanitize` option.
**This HTML parser does not accept that new JSON format yet.** Exporting is a
separate step, and nothing in this skill migrates that format or redacts
content for you.

OpenCode share pages can contain a lot of runtime data: tool calls, reasoning
parts, token counts, status objects, model metadata, and internal references.
This skill keeps the parts people usually need for handoff and review:

- user-visible prompts
- assistant-visible text responses
- message order
- session metadata
- clean Markdown output
- optional JSON output

## Use as a Codex skill

Copy this folder into your Codex skills directory:

```powershell
$env:USERPROFILE\.codex\skills\opencode-share
```

Then ask Codex to analyze a saved OpenCode share page, for example:

```text
Analyze this saved OpenCode share page and summarize the effective conversation:
.\share.html
```

For a page that still answers, the historical share URL form is:

```text
Analyze this OpenCode share session and summarize the effective conversation:
https://opncd.ai/share/SHARE_ID
```

## Use the parser directly

Requirements: Python 3.10 or newer. No third-party packages are required.

From a saved HTML file (the supported path):

```powershell
python .\scripts\extract_opencode_share.py ".\share.html" --out clean.md
```

With JSON output:

```powershell
python .\scripts\extract_opencode_share.py ".\share.html" --out clean.md --json-out clean.json
```

From a share URL (historical compatibility only):

```powershell
python .\scripts\extract_opencode_share.py "https://opncd.ai/share/SHARE_ID" --out clean.md
```

The parser also accepts `https://opencode.ai/s/SHARE_ID` and rewrites it to
the `opncd.ai/share/SHARE_ID` format before fetching. Official sharing is
discontinued, so this only applies to pages that still answer.

## Unicode handling

Share pages sometimes contain UTF-8 bytes that were decoded as Latin-1
("mojibake"). The parser repairs that on a best-effort basis, and only when
the whole string can be converted back without losing characters. Text that
mixes mojibake with characters outside Latin-1 (emoji, other scripts,
combining marks) is left exactly as supplied instead of being repaired
partially, because a partial repair would silently delete the characters it
cannot re-encode.

## Message parts

For the saved share HTML this parser supports, the visible text of a message is
read from that message's own parts array. The parser scans the serialized data
of the page to find the real end of the array, so nested references, nested
arrays, and quoted strings are handled, and the text of a long answer is never
cut off at a fixed length. Data that sits outside the parts array is not
collected, and a parts array that is never closed does not produce any text.

Only the script elements of a markup page are read as serialized data, and each
script element is scanned on its own, so page text and an unrelated script
cannot hide the payload. Input that does not start like markup is read as a raw
serialized fragment, even when its quoted text contains script tags.

When an HTML document has script elements, serialized data placed outside them
is not read. This is a limited serialized format reader, not a JavaScript
runtime.

This describes the saved HTML format the parser already supports. It does not
imply that a live share page is compatible with the parser.

## Output

The Markdown output contains:

```text
# OpenCode Share Session - Clean Transcript

## Metadata

Source: ...
Messages: ...
Share ID: ...
Title: ...
Model: ...
Tokens: ...

## Transcript

## 1. User

...

## 2. Assistant

...
```

The JSON output contains:

```json
{
  "metadata": {
    "source": "...",
    "share_id": "...",
    "title": "...",
    "model": {
      "id": "..."
    }
  },
  "message_count": 2,
  "messages": [
    {
      "id": "msg_...",
      "role": "user",
      "text": "..."
    }
  ]
}
```

## Exit codes

- `0`: extraction succeeded
- `2`: URL fetch or local file read failed
- `3`: no OpenCode share data was found
- `4`: share data existed, but no visible transcript text was extracted

## Tests

The test suite uses only the standard library:

```powershell
python -m unittest discover -s tests -v
```

## Multi-agent installation

Codex discovers skills under `.codex/skills`. Other tools may scan different
directories. If you want the same skill available elsewhere, copy or symlink
this folder into that tool's skills directory, such as `.opencode/skills` or
`.claude/skills`.

## Privacy

Only analyze share pages you are allowed to access. The parser reads data that
is embedded in a saved share page or a local HTML file you provide. It does not
authenticate, bypass access controls, or recover data that is not present in the
saved page.

## License

MIT
