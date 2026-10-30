---
name: opencode-share
description: Extract, clean, and summarize the conversation from an OpenCode session export (the JSON file written by `opencode session export`) or from a saved OpenCode share page (legacy HTML). Use when the user provides an OpenCode session export or a saved share page and wants the meaningful conversation, user inputs, assistant outputs, task handoff context, or a concise summary with tool noise, internal records, session metadata and reasoning blocks omitted. Official OpenCode sharing is discontinued, so the current route is a local JSON export.
---

# OpenCode Share

## Status

There are two input routes. Use the first one unless the user hands you a
saved share page.

1. **Native session export (JSON)** — the current route. OpenCode v2.2.1
   writes a session to a local JSON file with `opencode session export`.
2. **Saved share page (HTML)** — the legacy route, kept for pages that were
   archived before sharing was discontinued.

Official OpenCode sharing no longer works:

- The SDK documentation at <https://opencode.ai/docs/sdk/> states that
  `session.share` has been discontinued and now errors.
- The legacy changelog at <https://dev.opencode.ai/changelog/> records
  v1.19.1 (2026-10-15): official sharing and existing share links are
  unavailable.

## Workflow

### Route 1: native session export (JSON)

Start from the local export file the user provided. If no file is available,
explain the export command below. Export a session only when the user has
authorized the specific session and source; do not guess a session, enumerate
private histories or search home directories for them. Existing user
authorization takes precedence over asking for another confirmation.

```powershell
opencode session export SESSION_ID | Set-Content -Encoding utf8 session.json
```

Then convert it:

```powershell
python "$env:USERPROFILE\.codex\skills\opencode-share\scripts\extract_opencode_export.py" ".\session.json" --out ".\opencode-clean.md"
```

Add `--json-out ".\opencode-clean.json"` when the normalized JSON is useful.
Without `--out`, the Markdown transcript goes to stdout as UTF-8.

Normalized JSON is a filtered view, not an `opencode session import` input.
Keep the original export for reimporting.

The bundled synthetic example shows the whole route without touching a real
session. It is a small file with four messages, shaped like a native v2.2.1
export:

```powershell
python "$env:USERPROFILE\.codex\skills\opencode-share\scripts\extract_opencode_export.py" "$env:USERPROFILE\.codex\skills\opencode-share\examples\opencode-v2.synthetic.json"
```

The converter reads the export of OpenCode v2.2.1: the root must have an
`info` object and a `messages` array. The array order is authoritative, so
the conversation follows the exported order, not the message identifiers. The
pinned upstream schema sources are
[session-transfer.ts](https://github.com/anomalyco/opencode/blob/v2.2.1/packages/schema/src/session-transfer.ts)
and
[session-message.ts](https://github.com/anomalyco/opencode/blob/v2.2.1/packages/schema/src/session-message.ts).

The script outputs:

- A Markdown transcript with only the visible user text and the visible
  assistant text, plus a short summary of what was omitted.
- Optional normalized JSON with `--json-out path.json`, where every kept
  message keeps its position in the exported array as `source_index`.
- Typed failure messages. Exit code 3 means the export was rejected, exit
  code 4 means an output file could not be written. A failure message names
  the position of the offending record and the supported kinds; it never
  repeats a value that came out of the export.

The converter parses and filters the export file that is already on disk. The
output is a **filtered conversation view**: it is not a full archive and it is
not secret redaction, and it is not a safe-to-publish artifact. The visible
text is kept exactly as the export wrote it, so a secret that was part of the
visible text stays in the text. Tool calls, reasoning, system, skill, shell,
compaction and idle messages, agent/model/location switches, and attachment
names, paths and contents are left out and only counted. Review the result
before sharing it.

A raw export contains private content. When the export was written with the
native `--sanitize` option, the visible text is masked and the file holds
placeholders instead of the real messages; the converter keeps those
placeholders and cannot recover the original text.

### Route 2: saved share page (legacy HTML)

Use this only when the user gives you a saved share page file, or a share URL
that still answers. Share URL examples are historical compatibility only, and
a defunct link should not be retried.

```powershell
python "$env:USERPROFILE\.codex\skills\opencode-share\scripts\extract_opencode_share.py" ".\share.html" --out ".\opencode-clean.md"
```

The parser also accepts `https://opencode.ai/s/SHARE_ID` and rewrites it to
the `opncd.ai/share/SHARE_ID` form before fetching. Exit code 2 is a
fetch/read failure, 3 is missing share data, and 4 is an empty visible
transcript.

## Summarizing

After extraction, read the generated Markdown and produce the user-requested
artifact:

- For "summarize": provide a concise Chinese summary of the task, decisions,
  results, and any unresolved next steps.
- For handoff or continuation requests: identify the latest user intent,
  current state, files or URLs mentioned, and the next concrete action.
- For requests to show only effective messages: return or reference the clean
  Markdown transcript.

Do not include assistant reasoning parts, tool outputs, token/cost data,
hidden IDs, model metadata, or large raw file fragments unless the user
explicitly asks for forensic details.

## Notes

- Use the JSON route for any export file. The legacy HTML parser does not
  read the JSON export, and the JSON converter does not read saved share
  pages.
- The converter never overwrites the export or an existing output file, and
  it creates no output file when the export is rejected.
- Text is copied verbatim: Unicode, HTML entities, indentation and embedded
  newlines are not touched.
- Some sessions expose only public data. If requested content was never in
  the export or requires authentication, state that limitation clearly.
