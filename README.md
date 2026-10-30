# OpenCode Share

Parse an OpenCode session export that is already on your disk into a readable,
filtered conversation view.

Two input routes are supported:

| Route | Input | Script | Status |
| --- | --- | --- | --- |
| Native session export | `session.json` from `opencode session export` | `scripts/extract_opencode_export.py` | Current |
| Saved share page | `share.html` from the retired share feature | `scripts/extract_opencode_share.py` | Legacy, deprecated input |

The native JSON route is the one to use. The saved-HTML route is kept for
pages that were archived earlier.

Requirements: Python 3.10 or newer. No third-party packages are required, for
either route.

## Workflow 1: native session export (JSON)

OpenCode can export a session to a local JSON file. The separate export step
uses your selected OpenCode server, which may be local or remote. After that,
the Python converter reads only the saved file and contacts no service.

### Step 1: export the session yourself

Run this yourself, in the folder where you want the file. Replace
`SESSION_ID` with the session you want to export. If the session lives on a
remote OpenCode server, add the server address as `--server URL`.

```powershell
opencode session export SESSION_ID | Set-Content -Encoding utf8 session.json
```

The raw export includes session metadata and projected message records, not
just visible conversation text. It is not a database or event-history backup;
the CLI export omits unfinished assistant, shell and compaction records.

Two things to know about this file before you share it:

- A raw export contains private content: tool calls and their inputs and
  outputs, reasoning, system and skill text, and the names and paths of
  attachments.
- The native `--sanitize` option masks the visible text of the session, so the
  export then contains placeholders instead of the real messages. The
  converter keeps those placeholders as they are; their original text cannot
  be recovered from the export.

### Step 2: convert the export

```powershell
python .\scripts\extract_opencode_export.py .\session.json --out .\session.md
```

With normalized JSON output as well:

```powershell
python .\scripts\extract_opencode_export.py .\session.json --out .\session.md --json-out .\session.json.filtered.json
```

Without `--out`, the Markdown transcript goes to stdout as UTF-8, which makes
the converter usable in a pipe.

### One-command bundled example

The repository ships a synthetic export, so the whole route can be tried
without exporting anything of your own:

```powershell
python .\scripts\extract_opencode_export.py .\examples\opencode-v2.synthetic.json
```

The fixture is entirely synthetic: it contains a made-up session, made-up
messages and made-up identifiers only. It is a small file with four
messages, shaped like a native v2.2.1 export: one user message, one assistant
message with a reasoning block, a tool block and two visible text blocks, and
two messages of types that are not conversation text.

## What the converter produces

The converter parses and filters the export file that is already on your
disk. The output is a **filtered conversation view**: it is not a full archive
and it is not secret redaction. A secret that was already part of the visible
text stays in the text, so review the result yourself before you publish it.

Kept:

- the visible text of user messages,
- the visible text of assistant messages.

Dropped, and only counted in the summary:

- tool calls, including their inputs and outputs,
- reasoning,
- the message types `agent-switched`, `model-switched`, `location-switched`,
  `synthetic`, `system`, `skill`, `shell`, `compaction` and `idle`,
- the names, paths and contents of user attachments (their number is counted),

Session metadata such as identifiers, titles, project directory, model,
provider, agent and cost is also left out; metadata fields are not counted.

Retained nonblank text is copied verbatim. Nothing is unescaped, repaired or trimmed, so
Unicode, HTML entities, indentation and embedded newlines stay exactly as the
export wrote them. Two visible assistant text blocks of the same message are
joined with a blank line between them. Whitespace-only messages are omitted
and counted as having no visible text.

The Markdown output of the bundled example looks like this:

```text
# OpenCode Session Export - Filtered Conversation

Filtered view of a native OpenCode session export. It is not a full archive
and it is not secret redaction: secrets that were already part of the
visible text stay in the text.

## Summary

- Input kind: native OpenCode session export (JSON)
- Source messages: 4
- Retained messages: 2
- Omitted messages without visible text: 0
- Omitted message types: system 1, compaction 1
- Omitted assistant blocks: reasoning 1, tool 1
- User attachments: 0 (names, paths and contents are not included)

## Conversation

### 1. User

Please summarize this synthetic conversation.

### 2. Assistant

First visible answer block.

Second visible answer block.
```

The normalized JSON output contains the same conversation, plus the position
of every kept message in the exported array:

```json
{
  "format": "opencode-session-export-conversation",
  "version": 1,
  "note": "Filtered conversation view of an OpenCode session export. Not a full archive and not secret redaction.",
  "summary": {
    "source_messages": 4,
    "retained_messages": 2
  },
  "messages": [
    {
      "source_index": 0,
      "role": "user",
      "text": "..."
    }
  ]
}
```

`source_index` is the position of the message in the `messages` array of the
export, so a kept message can be traced back to the file. No other metadata
is copied.

The normalized JSON is a conversation view, not an input for
`opencode session import`. Keep the original export when you need an
importable archive.

### Supported export shape

The converter reads the export of OpenCode v2.2.1: an object with an `info`
object and a `messages` array. The array order is authoritative; identifiers
are never sorted and never used to restore the order. The pinned upstream
schema sources are:

- [packages/schema/src/session-transfer.ts](https://github.com/anomalyco/opencode/blob/v2.2.1/packages/schema/src/session-transfer.ts)
- [packages/schema/src/session-message.ts](https://github.com/anomalyco/opencode/blob/v2.2.1/packages/schema/src/session-message.ts)

Validation covers the fields used for extraction, rather than the complete
upstream schema:

- the file must be UTF-8, with or without a byte order mark, and valid JSON,
- the root must have an `info` object and a `messages` array,
- a `user` message needs a `text` string; non-null `files` must be an array,
- an `assistant` message needs a `content` array whose blocks are `text`,
  `reasoning` or `tool`,
- types outside the user/assistant records and the known omitted kinds listed
  above are rejected, so an unfamiliar type is not silently skipped.

An error message names the position of the offending record and the kinds
that are supported. It never repeats a value that came out of the export, so
a rejected export cannot leak its own content through the error output.

The legacy v1 export shape, where a message has `info` and `parts` instead of
a `type`, is rejected with a clear message.

### Files are never overwritten

The converter never writes over the export, and never over an existing
output. Output files are created exclusively, an output path may not alias
the input, and `--out` and `--json-out` may not be the same file. There is no
force flag. All validation finishes before any output file is created, so a
rejected export leaves no output behind. If one of two output files cannot be
written, the other one may already exist: the converter reports the failure
and does not promise that both files appear together.

### Exit codes

- `0`: conversion succeeded
- `2`: command line usage error
- `3`: the input is missing, unreadable, not valid UTF-8 or JSON, or not a
  supported OpenCode session export
- `4`: an output file could not be written, already exists, or aliases another
  path

## Workflow 2: saved share page (legacy, deprecated input)

This route is kept for share pages that were saved before sharing was
discontinued. It is deprecated: prefer the native JSON export above.

Official OpenCode sharing no longer works:

- The SDK documentation at <https://opencode.ai/docs/sdk/> states that
  `session.share` has been discontinued and now errors.
- The legacy changelog at <https://dev.opencode.ai/changelog/> records
  v1.19.1 (2026-10-15): official sharing and existing share links are
  unavailable.

So the supported workflow for this route is offline: take a saved share page
that you already have and parse the file. The URL examples below are kept as
historical compatibility for pages and files that were saved earlier. A
defunct share link is not worth retrying, and this tool does not bring
sharing back.

The legacy parser keeps the parts people usually need for handoff and review:
user-visible prompts, assistant-visible text, message order, session metadata,
clean Markdown output and optional JSON output.

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

### Unicode handling of the legacy route

Share pages sometimes contain UTF-8 bytes that were decoded as Latin-1
("mojibake"). The legacy parser repairs that on a best-effort basis, and only
when the whole string can be converted back without losing characters. Text
that mixes mojibake with characters outside Latin-1 (emoji, other scripts,
combining marks) is left exactly as supplied instead of being repaired
partially, because a partial repair would silently delete the characters it
cannot re-encode.

### Message parts of the legacy route

For the saved share HTML this parser supports, the visible text of a message
is read from that message's own parts array. The parser scans the serialized
data of the page to find the real end of the array, so nested references,
nested arrays, and quoted strings are handled, and the text of a long answer
is never cut off at a fixed length. Data that sits outside the parts array
is not collected, and a parts array that is never closed does not produce any
text.

Only the script elements of a markup page are read as serialized data, and
each script element is scanned on its own, so page text and an unrelated
script cannot hide the payload. Input that does not start like markup is
read as a raw serialized fragment, even when its quoted text contains script
tags.

When an HTML document has script elements, serialized data placed outside
them is not read. This is a limited serialized format reader, not a
JavaScript runtime.

This describes the saved HTML format the legacy parser already supports. It
does not imply that a live share page is compatible with the parser.

### Exit codes of the legacy route

- `0`: extraction succeeded
- `2`: URL fetch or local file read failed
- `3`: no OpenCode share data was found
- `4`: share data existed, but no visible transcript text was extracted

## Use as a Codex skill

Copy this folder into your Codex skills directory:

```powershell
$env:USERPROFILE\.codex\skills\opencode-share
```

Then ask Codex to analyze an exported session, for example:

```text
Analyze this OpenCode session export and summarize the effective conversation:
.\session.json
```

For a saved share page from before sharing was discontinued:

```text
Analyze this saved OpenCode share page and summarize the effective conversation:
.\share.html
```

## Tests

The test suite uses only the standard library:

```powershell
python -X utf8 -m unittest discover -s tests -v
```

## Multi-agent installation

Codex discovers skills under `.codex/skills`. Other tools may scan different
directories. If you want the same skill available elsewhere, copy or symlink
this folder into that tool's skills directory, such as `.opencode/skills` or
`.claude/skills`.

## Privacy

Only analyze sessions and pages that you are allowed to access. The converter
reads a local file that you provide. It does not authenticate, bypass access
controls, or recover data that is not present in that file. It does not
upload anything and it does not contact any service.

The legacy HTML script still fetches a URL when explicitly given one.

The converter parses and filters the export file that is already on your
disk. It does not rewrite the visible text, so what you typed stays exactly as
you typed it. The output is a filtered view, not a redacted one, and it is not
a safe-to-publish artifact: review it before you share it.

## License

MIT
