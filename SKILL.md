---
name: opencode-share
description: Extract, clean, and summarize the transcript from a saved OpenCode share page (legacy saved-HTML extractor). Use when the user provides a saved OpenCode share page file and wants the meaningful conversation, user inputs, assistant outputs, session metadata, task handoff context, or a concise summary without tool-call noise, internal state, paths, or reasoning artifacts. Official OpenCode sharing is discontinued, so this works on saved share HTML only.
---

# OpenCode Share (legacy saved-HTML extractor)

## Status

Official OpenCode sharing no longer works:

- The SDK documentation at <https://opencode.ai/docs/sdk/> states that
  `session.share` has been discontinued and now errors.
- The legacy changelog at <https://dev.opencode.ai/changelog/> records
  v1.19.1 (2026-10-15): official sharing and existing share links are
  unavailable.

Work from a saved share page file. Share URL examples are kept as historical
compatibility only, and a defunct link should not be retried.

OpenCode v2.2.1 can export a session locally instead. `opencode session
export --help` lists a JSON export and a `--sanitize` option, but this parser
does not accept that JSON format yet. Nothing here migrates that format or
redacts content for you.

## Workflow

Use the bundled parser first. Do not manually inspect the page unless the parser fails or the user needs debugging details.

From a saved share page:

```powershell
python "$env:USERPROFILE\.codex\skills\opencode-share\scripts\extract_opencode_share.py" ".\share.html" --out ".\opencode-clean.md"
```

From a share URL (historical compatibility only):

```powershell
python "$env:USERPROFILE\.codex\skills\opencode-share\scripts\extract_opencode_share.py" "https://opncd.ai/share/SHARE_ID" --out ".\opencode-clean.md"
```

The parser also accepts `https://opencode.ai/s/SHARE_ID` and rewrites it to the
`opncd.ai/share/SHARE_ID` form before fetching.

The script outputs:

- A clean Markdown transcript containing only user visible text and assistant visible text.
- Optional JSON with `--json-out path.json`.
- Session metadata, transcript counts, and typed failure messages.

## Summarizing

After extraction, read the generated Markdown and produce the user-requested artifact:

- For "summarize": provide a concise Chinese summary of the task, decisions, results, and any unresolved next steps.
- For handoff or continuation requests: identify the latest user intent, current state, files or URLs mentioned, and the next concrete action.
- For requests to show only effective messages: return or reference the clean Markdown transcript.

Do not include assistant reasoning parts, tool outputs, token/cost data, hidden IDs, model metadata, or large raw HTML fragments unless the user explicitly asks for forensic details.

## Notes

- OpenCode share pages often embed session data in one large script line with `$R[...]` references. The parser reconstructs message order, role, and visible `type:"text"` parts.
- The parser reads saved share HTML. It does not read the JSON export of OpenCode v2.2.1.
- The parser reads the script elements of a saved page. Input that does not start like markup is read as a raw serialized fragment.
- Some shared pages expose only public share data. If requested content was never included in the share HTML or requires authentication, state that limitation clearly.
- Treat exit code 2 as fetch/read failure, 3 as missing share data, and 4 as empty visible transcript.
